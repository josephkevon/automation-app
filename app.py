import threading
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, abort, make_response
import time
from instagrapi import Client
from openai import OpenAI
import random
import os
import json
from instagrapi.exceptions import LoginRequired, PleaseWaitFewMinutes, RateLimitError

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="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",
)

bot_running = False
bot_thread = None


app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Required for sessions
cl = Client()


def patch_instagrapi():
    """
    Monkey patch to fix instagrapi Pydantic validation errors
    """
    try:
        from instagrapi.types import Media
        from pydantic import validator
        
        # Create a more flexible validator for clips_metadata
        def flexible_clips_metadata_validator(cls, v):
            if v is None:
                return {}
            if isinstance(v, dict):
                # Fix original_sound_info if it's None
                if 'original_sound_info' in v and v['original_sound_info'] is None:
                    v['original_sound_info'] = {}
                
                # Fix reusable_text_info if it's a list instead of dict
                if 'reusable_text_info' in v and isinstance(v['reusable_text_info'], list):
                    v['reusable_text_info'] = {'text_elements': v['reusable_text_info']}
                
                return v
            return {}
        
        # Apply the patch if the Media class exists
        if hasattr(Media, '__validators__'):
            # Add our flexible validator
            Media.__validators__['clips_metadata'] = flexible_clips_metadata_validator
            print("✅ Successfully patched instagrapi validation")
        
    except ImportError:
        print("⚠️ Could not import instagrapi types for patching")
    except Exception as e:
        print(f"⚠️ Failed to patch instagrapi: {e}")

# Apply the patch when the module loads
patch_instagrapi()

# Rest of your existing code...

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/page2")
def page2():
    return render_template("page2.html")

@app.route("/instadm")
def instadm():
    return render_template("instadm.html")

@app.route("/sales")
def sales():
    return render_template("sales.html")

# Add this route to your Flask application

# Add these routes to your Flask application

@app.route("/follower_config", methods=["POST"])
def follower_config():
    """Handle follower campaign configuration"""
    # Get form data
    USERNAME = request.form.get("username")
    PASSWORD = request.form.get("password")
    TARGET = request.form.get("target_account")
    DM_LIMIT = request.form.get("dm_limit")
    DELAY_SECONDS = request.form.get("delay_seconds")
    MESSAGE = request.form.get("message")
    
    # Remove @ symbol if present in target account
    if TARGET and TARGET.startswith('@'):
        TARGET = TARGET[1:]
    
    # Store data in session for later use
    session['follower_username'] = USERNAME
    session['follower_password'] = PASSWORD
    session['follower_target'] = TARGET
    session['follower_dm_limit'] = int(DM_LIMIT) if DM_LIMIT else 8
    session['follower_delay'] = int(DELAY_SECONDS) if DELAY_SECONDS else 3
    session['follower_message'] = MESSAGE
    
    # Log the received data (for debugging - remove password logging in production)
    print("Follower Campaign Configuration Received:")
    print(f"Username: {USERNAME}")
    print(f"Target: {TARGET}")
    print(f"DM Limit: {DM_LIMIT}")
    print(f"Delay: {DELAY_SECONDS} seconds")
    print(f"Message: {MESSAGE[:50]}..." if MESSAGE else "No message content")
    
    # Render the follower run page with the configuration data
    return render_template("follower_run.html", 
                         username=USERNAME,
                         password=PASSWORD,
                         target_account=TARGET,
                         dm_limit=DM_LIMIT,
                         delay_seconds=DELAY_SECONDS,
                         message=MESSAGE,
                         status="Configuration complete - ready to launch!")


@app.route("/run_follower_tool", methods=["POST"])
def run_follower_tool():
    """Execute the follower messaging campaign"""
    # Get data from form or session
    USERNAME = request.form.get("username") or session.get('follower_username')
    PASSWORD = request.form.get("password") or session.get('follower_password')
    TARGET = request.form.get("target_account") or session.get('follower_target')
    DM_LIMIT = int(request.form.get("dm_limit", 0)) or session.get('follower_dm_limit', 8)
    DELAY_SECONDS = random.randint(3, 10) #if not request.form.get("delay_seconds") else int(request.form.get("delay_seconds"))
    MESSAGE = request.form.get("message") or session.get('follower_message')
    
    # Remove @ symbol if present
    if TARGET and TARGET.startswith('@'):
        TARGET = TARGET[1:]
    
    error = None
    success_message = None
    
    # Validate inputs
    if not all([USERNAME, PASSWORD, TARGET, MESSAGE]):
        error = "Missing configuration data. Please configure your campaign first."
        return render_template("follower_run.html", 
                             username=USERNAME,
                             target_account=TARGET,
                             dm_limit=DM_LIMIT,
                             delay_seconds=DELAY_SECONDS,
                             message=MESSAGE,
                             error=error)
    
    try:
        # Set up file paths
        SETTINGS_FILE = f"{USERNAME}_follower_settings.json"
        LOG_FILE = f"{USERNAME}_follower_already_messaged.txt"
        
        # Initialize Instagram client
        cl = Client()
        
        # Load previous session if available
        if os.path.exists(SETTINGS_FILE):
            try:
                cl.load_settings(SETTINGS_FILE)
                print("Previous session loaded")
            except Exception as e:
                print(f"Failed to load previous session: {e}")
        
        # Login to Instagram
        try:
            cl.login(USERNAME, PASSWORD)
            print(f"Successfully logged in as {USERNAME}")
        except Exception as e:
            print("Login failed, retrying with fresh settings:", e)
            cl.set_settings({})
            try:
                cl.login(USERNAME, PASSWORD)
                print("Login successful with fresh settings")
            except Exception as login_error:
                error = f"Login failed: {str(login_error)}. Please check your username and password."
                return render_template("follower_run.html", 
                                     username=USERNAME,
                                     target_account=TARGET,
                                     dm_limit=DM_LIMIT,
                                     delay_seconds=DELAY_SECONDS,
                                     message=MESSAGE,
                                     error=error)
        
        # Save session to reuse later
        cl.dump_settings(SETTINGS_FILE)
        
        # Load already messaged usernames
        already_messaged = set()
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r") as f:
                already_messaged = set(line.strip() for line in f.readlines())
        
        # Get target user's followers
        try:
            user_id = cl.user_id_from_username(TARGET)
            followers = cl.user_followers(user_id)
            print(f"Found {len(followers)} followers for @{TARGET}")
        except Exception as e:
            error = f"Failed to get followers for @{TARGET}. Make sure the account exists and is public."
            return render_template("follower_run.html", 
                                 username=USERNAME,
                                 target_account=TARGET,
                                 dm_limit=DM_LIMIT,
                                 delay_seconds=DELAY_SECONDS,
                                 message=MESSAGE,
                                 error=error)
        
        # Send messages to followers
        sent_count = 0
        already_messaged_count = 0
        failed_count = 0
        
        with open(LOG_FILE, "a") as log_file:
            for follower in followers.values():
                username = follower.username
                
                # Skip if already messaged
                if username in already_messaged:
                    print(f"Skipping @{username} (already messaged)")
                    already_messaged_count += 1
                    continue
                
                # Check if limit reached
                if sent_count >= DM_LIMIT:
                    print(f"DM limit of {DM_LIMIT} reached. Stopping.")
                    break
                
                try:
                    # Send the direct message
                    cl.direct_send(MESSAGE, [follower.pk])
                    print(f"✅ DM sent to @{username}")
                    
                    # Log the username to avoid sending again
                    log_file.write(username + "\n")
                    already_messaged.add(username)
                    sent_count += 1
                    
                    # Wait to avoid spam detection
                    time.sleep(DELAY_SECONDS)
                    
                except Exception as e:
                    print(f"❌ Failed to message @{username}: {e}")
                    failed_count += 1
                    continue
        
        # Prepare success message
        success_message = f"Campaign completed! Messages sent: {sent_count}, Already messaged: {already_messaged_count}, Failed: {failed_count}"
        print(success_message)
        
        # Return results to template
        return render_template("follower_run.html", 
                             username=USERNAME,
                             target_account=TARGET,
                             dm_limit=DM_LIMIT,
                             delay_seconds=DELAY_SECONDS,
                             message=MESSAGE,
                             success_message=success_message,
                             messages_sent=sent_count,
                             already_messaged=already_messaged_count,
                             failed_messages=failed_count)
        
    except Exception as e:
        error = f"An unexpected error occurred: {str(e)}"
        print(f"Error in follower tool: {e}")
        return render_template("follower_run.html", 
                             username=USERNAME,
                             target_account=TARGET,
                             dm_limit=DM_LIMIT,
                             delay_seconds=DELAY_SECONDS,
                             message=MESSAGE,
                             error=error)


# Update your existing follower route to render the input template
@app.route("/follower")
def follower():
    return render_template("follower.html")

@app.route("/resulte", methods=["GET", "POST"])
def resulte():
    if request.method == "POST":
        # Get form data
        username = request.form.get("username")
        password = request.form.get("password")
        niche = request.form.get("niche") or request.form.get("customNiche")
        amount_of_dms = request.form.get("messageCount")
        message = request.form.get("messageContent")
        
        # Convert message count to integer if provided
        if amount_of_dms:
            try:
                amount_of_dms = int(amount_of_dms)
            except ValueError:
                amount_of_dms = 0
        
        # Store data in session for use in other routes
        session['username'] = username
        session['password'] = password
        session['niche'] = niche
        session['amount_of_dms'] = amount_of_dms
        session['message'] = message
        
        # Log the received data (for debugging - remove password logging in production)
        print("Instagram Configuration Received:")
        print(f"Username: {username}")
        print(f"Niche: {niche}")
        print(f"Message Count: {amount_of_dms}")
        print(f"Message Content: {message[:50]}..." if message else "No message content")
        
        # Render the results page with the configuration data
        return render_template("resulte.html", 
                             username=username,
                             password=password,
                             niche=niche,
                             message_count=amount_of_dms,
                             message_content=message)
    
    # If GET request, redirect to instadm page
    return render_template("instadm.html")

@app.route("/runinstadm", methods=["POST", "GET"])
def run_instadm():
    # Get data from session
    username = session.get('username')
    password = session.get('password')
    niche = session.get('niche')
    amount_of_dms = session.get('amount_of_dms')
    message = session.get('message')
    
    error = None
    success_message = None
    
    if not all([username, password, niche, amount_of_dms, message]):
        error = "Missing configuration data. Please configure your campaign first."
        return render_template("resulte.html", 
                             username=username,
                             password=password,
                             niche=niche,
                             message_count=amount_of_dms,
                             message_content=message,
                             error=error)
    
    try:
        # Login to Instagram with better error handling
        SETTINGS_FILE = f"{username}_settings.json"
        
        # Initialize client
        cl = Client()
        
        # Load previous session if available
        if os.path.exists(SETTINGS_FILE):
            try:
                cl.load_settings(SETTINGS_FILE)
                print("Previous session loaded")
            except Exception as e:
                print(f"Failed to load previous session: {e}")
        
        # Login with retry logic
        try:
            cl.login(username, password)
            print(f"Successfully logged in as {username}")
        except Exception as e:
            print("Login failed, retrying with fresh settings:", e)
            cl.set_settings({})
            try:
                cl.login(username, password)
                print("Login successful with fresh settings")
            except Exception as login_error:
                error = f"Login failed: {str(login_error)}. Please check your username and password."
                return render_template("resulte.html", 
                                     username=username,
                                     password=password,
                                     niche=niche,
                                     message_count=amount_of_dms,
                                     message_content=message,
                                     error=error)
        
        # Save session
        cl.dump_settings(SETTINGS_FILE)
        
        # Try multiple approaches to fetch posts
        medias = []
        approaches = [
            ("hashtag_medias_recent", lambda: cl.hashtag_medias_recent(niche, amount=amount_of_dms)),
            ("hashtag_medias_top", lambda: cl.hashtag_medias_top(niche, amount=min(20, amount_of_dms))),
            ("search_users", lambda: get_users_from_hashtag_search(cl, niche, amount_of_dms)),
        ]
        
        for approach_name, approach_func in approaches:
            try:
                print(f"Trying approach: {approach_name}")
                if approach_name == "search_users":
                    # Alternative: Get users who post about the hashtag
                    target_users = approach_func()
                    if target_users:
                        print(f"Found {len(target_users)} users from hashtag search")
                        # Convert users to a format we can work with
                        medias = []
                        for user in target_users:
                            # Create a mock media object with user info
                            class MockMedia:
                                def __init__(self, user):
                                    self.user = user
                            medias.append(MockMedia(user))
                        break
                else:
                    medias = approach_func()
                    if medias:
                        print(f"Success with {approach_name}: {len(medias)} posts")
                        break
                        
            except Exception as e:
                error_str = str(e)
                print(f"{approach_name} failed: {error_str}")
                
                # If it's the validation error, try a workaround
                if "validation errors for Media" in error_str or "clips_metadata" in error_str:
                    print("Validation error detected, trying user search instead...")
                    continue
        
        # If all approaches failed, try the follower-based approach
        if not medias:
            try:
                print("All hashtag approaches failed. Trying to find users who engage with the hashtag...")
                # Search for recent posts and get commenters/likers instead
                medias = get_hashtag_engagers(cl, niche, amount_of_dms)
            except Exception as final_error:
                print(f"Final fallback also failed: {final_error}")
                error = f"Unable to find users for #{niche}. The hashtag might be restricted or Instagram's API has changed. Try using the 'Follower Tool' instead, or try a different hashtag like #style #ootd #clothing"
                return render_template("resulte.html", 
                                     username=username,
                                     password=password,
                                     niche=niche,
                                     message_count=amount_of_dms,
                                     message_content=message,
                                     error=error)
        
        if not medias:
            error = f"No posts found for hashtag #{niche}. Try a different hashtag."
            return render_template("resulte.html", 
                                 username=username,
                                 password=password,
                                 niche=niche,
                                 message_count=amount_of_dms,
                                 message_content=message,
                                 error=error)
        
        messages_sent = 0
        already_messaged = 0
        failed_messages = 0
        
        for media in medias:
            try:
                # Read existing usernames from file
                try:
                    with open('usernames.txt', 'r') as file:
                        usernames = [line.strip() for line in file.readlines()]
                except FileNotFoundError:
                    usernames = []
                
                # Safe access to user data
                try:
                    account = media.user.username
                except AttributeError:
                    print("Warning: Media object missing user data, skipping...")
                    continue
                
                # Check if the account has already been messaged
                if account in usernames:
                    print(f"{account} has already been messaged.")
                    already_messaged += 1
                    continue
                
                try:
                    # Send the direct message
                    user_id = cl.user_id_from_username(account)
                    cl.direct_send(message, [user_id])
                    messages_sent += 1
                    
                    print(f"Message sent to {account}: {message}")
                    
                    # Append the username to the file to avoid sending messages again
                    with open('usernames.txt', 'a') as file:
                        file.write(account + '\n')
                    
                    # Add delay between messages to avoid being blocked
                    time.sleep(random.randint(3, 7))  # Random delay
                    
                except Exception as e:
                    print(f"Failed to send message to {account}: {e}")
                    failed_messages += 1
                    continue
                    
            except Exception as e:
                print(f"Error processing media: {e}")
                failed_messages += 1
                continue
        
        success_message = f"Campaign completed! Messages sent: {messages_sent}, Already messaged: {already_messaged}, Failed: {failed_messages}"
        print(success_message)
        
    except Exception as e:
        error = f"Campaign failed: {str(e)}"
        print(error)
    
    # Return to results page with status
    return render_template("resulte.html", 
                         username=username,
                         password=password,
                         niche=niche,
                         message_count=amount_of_dms,
                         message_content=message,
                         success_message=success_message,
                         error=error,
                         messages_sent=messages_sent if 'messages_sent' in locals() else 0,
                         already_messaged=already_messaged if 'already_messaged' in locals() else 0,
                         failed_messages=failed_messages if 'failed_messages' in locals() else 0)
# Optional: API endpoint to get configuration status
@app.route("/api/status")
def get_status():
    return jsonify({
        "status": "active",
        "message": "Campaign is running successfully"
    })







#sales automation
# Replace your existing sales_automation and sales_automation2 routes with these:

@app.route("/sales_automation", methods=["GET", "POST"])
def sales_automation():
    if request.method == "POST":
        # Get the username and password from the profile setup form
        USERNAME = request.form.get("username")
        PASSWORD = request.form.get("password")
        
        # Store in session for later use
        session['profile_username'] = USERNAME
        session['profile_password'] = PASSWORD
        
        # Log the received data (for debugging - remove password logging in production)
        print("Profile Setup Received:")
        print(f"Username: {USERNAME}")
        
        status = "Profile configured successfully!"
        
        # Render the sales automation dashboard page
        return render_template("sales_automation.html", 
                             username=USERNAME, 
                             password=PASSWORD, 
                             status=status)
    
    # If GET request, just render the page normally
    return render_template("sales_automation.html")


def run_sales_bot(username, password):
    """Function to run the sales bot in a separate thread"""
    global bot_running
    
    SYSTEM_PROMPT = """You are a master salesman helping me respond to potential clients. I'm selling an AI bot that sends Instagram DMs and books meetings automatically.

Key points about my service:
- Bot finds ideal customers on Instagram using keywords/competitor scraping
- Sends hundreds of DMs automatically
- AI handles conversations and books meetings when people reply
- Client gets qualified meetings without any manual work

Your job:
- Reply in 1-2 sentences + ask a question
- Match their tone, sound like an old friend helping them
- Don't be pushy or salesy
- Goal is to book a meeting (but take your time)
- Use simple 5th grade level words
- Handle objections by asking "can I ask a question?" or "can I make a suggestion?"

Common objections: "need to think", "not interested", "tried before", "sounds too good"
Handle with: "Before I lose you, is it that you're unsure this will work?" / "Let's do a quick 5-10 min call"

Reply only with the response, nothing else."""
    
    def chat(prompt, conversation_log=""):
        # Limit conversation log to last 400 characters to save tokens
        if len(conversation_log) > 400:
            conversation_log = "..." + conversation_log[-400:]

        full_prompt = f"{SYSTEM_PROMPT}\n\nConversation history: {conversation_log}\n\nTheir message: {prompt}\n\nYour reply:"

        try:
            # Try multiple model options in order of preference
            models_to_try = [
                "anthropic/claude-3-haiku",  # Usually available and affordable
                "meta-llama/llama-3.1-8b-instruct",  # Free alternative
                "google/gemma-2-9b-it",  # Another free option
                "mistralai/mistral-7b-instruct",  # Fallback option
            ]
            
            for model in models_to_try:
                try:
                    completion = client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": full_prompt}],
                        max_tokens=150,
                        temperature=0.7
                    )
                    return completion.choices[0].message.content.strip()
                except Exception as model_error:
                    print(f"⚠️ Model {model} failed: {model_error}")
                    continue
            
            # If all models fail, return fallback message
            return "Thanks for your message! I'll get back to you soon with more details."
            
        except Exception as e:
            error_msg = str(e).lower()
            if "402" in error_msg or "credits" in error_msg:
                print("❌ OpenRouter credits exhausted! Please add credits at https://openrouter.ai/settings/credits")
                return "Thanks for your message! I'll get back to you soon."
            elif "403" in error_msg or "key" in error_msg:
                print("❌ API key issue. Using fallback response.")
                return "Thanks for reaching out! Let me get back to you with more details."
            else:
                print(f"❌ Chat API error: {e}")
                return "Thanks for reaching out! Let me get back to you with more details."

    def safe_get_username(cl, user_id, max_retries=3):
        """Safely get username with multiple fallback methods"""
        # Try different methods to get username
        methods = [
            lambda: cl.user_info(user_id).username,
            lambda: cl.user_short_gql(user_id).username,
            lambda: f"user_{str(user_id)[-8:]}"  # Fallback with last 8 digits of ID
        ]
        
        for attempt in range(max_retries):
            for method_idx, method in enumerate(methods):
                try:
                    return method()
                except KeyError as e:
                    if 'data' in str(e) and method_idx < len(methods) - 1:
                        print(f"⚠️ Instagram GraphQL 'data' key error, trying fallback method...")
                        continue
                    elif method_idx == len(methods) - 1:
                        return f"user_{str(user_id)[-8:]}"
                except Exception as e:
                    print(f"⚠️ Error fetching user info (method {method_idx+1}, attempt {attempt + 1}): {e}")
                    if method_idx < len(methods) - 1:
                        continue
                    elif attempt < max_retries - 1:
                        time.sleep(random.randint(5, 15))
                        break
        
        return f"user_{str(user_id)[-8:]}"

    def safe_instagram_login():
        """Login with better error handling and session management"""
        cl = Client()
        SETTINGS_PATH = "insta_session.json"

        # Configure client settings for better stability
        cl.delay_range = [3, 8]  # Increased delay range
        cl.request_timeout = 30
        
        # Set user agent to look more natural
        cl.set_user_agent("Instagram 276.0.0.27.98 Android (33/13; 420dpi; 1080x2340; samsung; SM-G991B; o1s; exynos2100; en_US; 458229237)")

        if os.path.exists(SETTINGS_PATH):
            try:
                print("🔄 Loading saved session...")
                cl.load_settings(SETTINGS_PATH)
                # Test the session
                cl.login(username, password, relogin=True)
                print("✅ Session loaded successfully")
                return cl
            except Exception as e:
                print(f"⚠️ Failed to load session: {e}")
                print("🔄 Logging in fresh...")
                # Remove corrupted session file
                try:
                    os.remove(SETTINGS_PATH)
                except:
                    pass

        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"🔑 Login attempt {attempt + 1}...")
                cl.login(username, password)
                cl.dump_settings(SETTINGS_PATH)
                print("✅ Fresh login successful")
                return cl
            except Exception as e:
                error_msg = str(e).lower()
                print(f"❌ Login attempt {attempt + 1} failed: {e}")
                
                if "challenge" in error_msg:
                    print("🔐 Challenge required. Please complete it manually and restart the bot.")
                    raise e
                elif "checkpoint" in error_msg:
                    print("⚠️ Account checkpoint detected. Please verify your account manually.")
                    raise e
                elif attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 60  # Increased wait time
                    print(f"⏳ Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                else:
                    raise e

    def get_threads_with_retry(cl, max_retries=5):
        """Get threads with exponential backoff retry and better error handling"""
        for attempt in range(max_retries):
            try:
                # Try different amounts to avoid hitting limits
                amounts_to_try = [3, 5, 10]
                
                for amount in amounts_to_try:
                    try:
                        threads = cl.direct_threads(amount=amount)
                        if threads:  # If we got threads, return them
                            return threads
                    except Exception as amount_error:
                        print(f"⚠️ Failed with amount {amount}: {amount_error}")
                        continue
                
                # If all amounts failed, try once more with amount=1
                return cl.direct_threads(amount=1)
                
            except Exception as e:
                error_msg = str(e).lower()

                if "500" in error_msg or "server" in error_msg or "internal" in error_msg:
                    wait_time = min(300, (2 ** attempt) * 10 + random.randint(5, 15))
                    print(f"🔄 Instagram server error (attempt {attempt + 1}). Waiting {wait_time}s...")
                elif "rate limit" in error_msg or "429" in error_msg or "spam" in error_msg:
                    wait_time = min(600, 180 + (attempt * 120) + random.randint(60, 180))
                    print(f"⏱️ Rate limited (attempt {attempt + 1}). Waiting {wait_time}s...")
                elif "login" in error_msg or "unauthorized" in error_msg:
                    print("🔐 Login session expired. Need to re-authenticate.")
                    raise e
                else:
                    wait_time = min(180, 30 * (attempt + 1))
                    print(f"❌ Unexpected error (attempt {attempt + 1}): {e}")
                    print(f"⏳ Waiting {wait_time}s...")

                if attempt < max_retries - 1:
                    time.sleep(wait_time)
                else:
                    print("❌ Max retries reached for getting threads")
                    raise e

        return []  # Return empty list if everything fails

    def send_message_with_retry(cl, message, user_ids, max_retries=3):
        """Send message with retry logic and better error handling"""
        for attempt in range(max_retries):
            try:
                cl.direct_send(message, user_ids)
                return True
            except Exception as e:
                error_msg = str(e).lower()

                if "500" in error_msg or "server" in error_msg:
                    wait_time = min(120, (attempt + 1) * 20)
                    print(f"🔄 Send failed due to server error (attempt {attempt + 1}). Waiting {wait_time}s...")
                elif "rate limit" in error_msg or "429" in error_msg:
                    wait_time = min(300, 60 + (attempt * 60))
                    print(f"⏱️ Send rate limited (attempt {attempt + 1}). Waiting {wait_time}s...")
                elif "spam" in error_msg:
                    print("⚠️ Message flagged as spam. Adjusting future messages...")
                    wait_time = 180
                else:
                    wait_time = min(90, 30 * (attempt + 1))
                    print(f"❌ Send error (attempt {attempt + 1}): {e}")

                if attempt < max_retries - 1:
                    time.sleep(wait_time)
                else:
                    print("❌ Failed to send message after all retries")
                    return False

    try:
        # Initialize Instagram client
        cl = safe_instagram_login()

        # Store already replied message IDs with timestamp cleanup
        seen_messages = {}  # Changed to dict to store timestamps
        max_seen_messages = 1000  # Prevent memory issues

        # Adaptive polling intervals
        base_interval = 200  # Slightly increased base interval
        max_interval = 800   # Increased max interval
        current_interval = base_interval
        consecutive_errors = 0

        print("🤖 Live Instagram DM bot is now running...")
        print(f"⏱️ Checking for messages every {current_interval} seconds")
        print("💳 Note: Check OpenRouter credits at https://openrouter.ai/settings/credits")

        while bot_running:
            try:
                # Clean up old seen messages periodically
                current_time = time.time()
                if len(seen_messages) > max_seen_messages:
                    # Remove messages older than 24 hours
                    cutoff_time = current_time - (24 * 60 * 60)
                    seen_messages = {k: v for k, v in seen_messages.items() if v > cutoff_time}
                    print(f"🧹 Cleaned up old message history. Now tracking {len(seen_messages)} messages.")

                # Get latest threads with retry
                threads = get_threads_with_retry(cl)

                # Reset error counter on success
                consecutive_errors = 0
                current_interval = max(base_interval, current_interval - 30)

                message_found = False

                for thread in threads:
                    if not thread.messages:
                        continue

                    message = thread.messages[0]
                    msg_id = message.id
                    msg_text = message.text.lower() if message.text else ""

                    # Ignore your own messages
                    if message.user_id == cl.user_id:
                        continue

                    # Only reply to new messages
                    if msg_id not in seen_messages:
                        seen_messages[msg_id] = current_time
                        message_found = True

                        # Use safe username fetching with enhanced fallback
                        sender = safe_get_username(cl, message.user_id)

                        print(f"💬 {sender} said: {msg_text}")

                        # Handle log files
                        log_filename = f"{sender}log.txt"
                        if not os.path.exists(log_filename):
                            with open(log_filename, "w", encoding="utf-8") as initial_msg:
                                initial_msg.write("""Hey, are you guys able to handle more clients? 

we are doing a free 14-day service for businesses like yours.
our system sends 150 DMs a day to people likely to need your service.
are you open to that?
""")

                        # Log the incoming message
                        with open(log_filename, "a", encoding="utf-8") as log_file:
                            log_file.write(f"{sender}: {msg_text}\n")

                        # Skip own messages (double check)
                        if sender.lower() == username.lower():
                            print("Skipping own message.")
                            continue

                        if msg_text.strip() == "exit":
                            print("Exit command received, skipping...")
                            continue

                        # Read conversation log
                        try:
                            with open(log_filename, "r", encoding="utf-8") as log_file:
                                log_content = log_file.read()
                                if len(log_content) > 800:
                                    log_content = "..." + log_content[-800:]
                        except FileNotFoundError:
                            log_content = ""

                        # Generate reply with enhanced error handling
                        try:
                            reply = chat(msg_text, log_content)
                            if reply and len(reply.strip()) > 0:
                                print("🤖 Bot:", reply)

                                # Send reply with retry
                                if send_message_with_retry(cl, reply, [message.user_id]):
                                    # Log the reply only if sent successfully
                                    with open(log_filename, "a", encoding="utf-8") as log_file:
                                        log_file.write(f"Bot: {reply}\n")
                                    print("✅ Message sent successfully")
                                else:
                                    print("❌ Failed to send message")
                            else:
                                print("⚠️ Generated reply was empty, skipping...")

                        except Exception as e:
                            print(f"❌ Error generating/sending reply: {e}")

                        # Add delay between processing messages (increased for stability)
                        time.sleep(random.randint(15, 30))

                if message_found:
                    print(f"✅ Processed messages. Next check in {current_interval} seconds")
                else:
                    print(f"📭 No new messages. Next check in {current_interval} seconds")

                # Wait before checking again
                time.sleep(current_interval)

            except Exception as e:
                consecutive_errors += 1
                error_msg = str(e).lower()

                if "500" in error_msg or "server" in error_msg:
                    current_interval = min(max_interval, current_interval + 60)
                    wait_time = current_interval + random.randint(60, 180)
                    print(f"🔴 Instagram server issues detected. Waiting {wait_time} seconds...")
                    print(f"📈 Increased polling interval to {current_interval} seconds")
                elif "login" in error_msg or "challenge" in error_msg or "checkpoint" in error_msg:
                    print("🔐 Authentication issue detected. Attempting re-login...")
                    try:
                        cl = safe_instagram_login()
                        wait_time = 120
                    except Exception as login_error:
                        print(f"❌ Re-login failed: {login_error}")
                        wait_time = 900  # Wait 15 minutes on login failure
                        print("⚠️ Consider manually logging into Instagram to resolve any challenges.")
                elif "rate limit" in error_msg or "429" in error_msg:
                    wait_time = min(600, 180 + (consecutive_errors * 120))
                    current_interval = min(max_interval, current_interval + 120)
                    print(f"⏱️ Rate limited. Waiting {wait_time} seconds...")
                    print(f"📈 Increased polling interval to {current_interval} seconds")
                else:
                    wait_time = min(300, 60 * consecutive_errors)
                    print(f"⚠️ Error (#{consecutive_errors}): {e}")
                    print(f"⏳ Waiting {wait_time} seconds before retry...")

                time.sleep(wait_time)
                
    except Exception as e:
        print(f"❌ Bot crashed: {e}")
        print("🔄 You may need to restart the bot or check your Instagram account status.")
        bot_running = False


@app.route("/sales_automation2", methods=["GET", "POST"])
def sales_automation2():
    global bot_running, bot_thread
    
    if request.method == "POST":
        # Get credentials from form or session
        USERNAME = request.form.get("username") or session.get('profile_username')
        PASSWORD = request.form.get("password") or session.get('profile_password')
        
        if not USERNAME or not PASSWORD:
            error = "No credentials found. Please set up your profile first."
            return render_template("sales_automation.html", error=error)
        
        if not bot_running:
            # Start the bot in a separate thread
            bot_running = True
            bot_thread = threading.Thread(target=run_sales_bot, args=(USERNAME, PASSWORD))
            bot_thread.daemon = True  # Thread will die when main program exits
            bot_thread.start()
            
            success_message = "🤖 Sales automation bot started successfully! Check the console for live updates."
            print("🚀 Sales automation bot has been started!")
            
        else:
            success_message = "Bot is already running!"
        
        return render_template("sales_automation.html", 
                             username=USERNAME,
                             status="Bot is running...",
                             success_message=success_message)
    
    # If GET request, just render the page
    return render_template("sales_automation.html")


@app.route("/stop_bot", methods=["POST"])
def stop_bot():
    """Route to stop the bot"""
    global bot_running
    bot_running = False
    
    success_message = "Bot has been stopped successfully."
    return render_template("sales_automation.html", 
                         success_message=success_message,
                         status="Bot stopped")


@app.route("/bot_status")
def bot_status():
    """API endpoint to check bot status"""
    global bot_running
    return jsonify({
        "running": bot_running,
        "status": "Bot is running" if bot_running else "Bot is stopped"
    })


if __name__ == "__main__":
    app.run(debug=True)
