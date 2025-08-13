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
    DELAY_SECONDS = random.randint(3, 10) if not request.form.get("delay_seconds") else int(request.form.get("delay_seconds"))
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
        # Login to Instagram
        cl.login(username, password)
        print(f"Successfully logged in as {username}")
        
        # Fetch recent posts from the hashtag
        medias = cl.hashtag_medias_recent(niche, amount=amount_of_dms)
        
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
                
                account = media.user.username
                
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
                    time.sleep(2)  # 2-second delay
                    
                except Exception as e:
                    print(f"Failed to send message to {account}: {e}")
                    failed_messages += 1
                    continue
                    
            except Exception as e:
                print(f"Error processing media: {e}")
                continue
        
        success_message = f"Campaign completed! Messages sent: {messages_sent}, Already messaged: {already_messaged}, Failed: {failed_messages}"
        print(success_message)
        
    except Exception as e:
        error = f"Login failed: {str(e)}. Please check your username and password."
        print(error)
    
    # Return to results page with status
    return render_template("resulte.html", 
                         username=username,
                         password=password,
                         niche=niche,
                         message_count=amount_of_dms,
                         message_content=message,
                         success_message=success_message,
                         error=error)

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
            completion = client.chat.completions.create(
                model="gpt-5",
                messages=[{"role": "user", "content": full_prompt}],
                max_tokens=150
            )
            return completion.choices[0].message.content.strip()
        except Exception as e:
            error_msg = str(e).lower()
            if "402" in error_msg or "credits" in error_msg:
                print("❌ OpenRouter credits exhausted! Please add credits at https://openrouter.ai/settings/credits")
                return "Thanks for your message! I'll get back to you soon."
            else:
                print(f"❌ Chat API error: {e}")
                return "Thanks for reaching out! Let me get back to you with more details."

    def safe_get_username(cl, user_id, max_retries=3):
        """Safely get username with fallback and retry logic"""
        for attempt in range(max_retries):
            try:
                user_info = cl.user_info(user_id)
                return user_info.username
            except KeyError as e:
                if 'data' in str(e):
                    print(f"⚠️ Instagram GraphQL 'data' key error (attempt {attempt + 1})")
                    if attempt < max_retries - 1:
                        time.sleep(random.randint(10, 30))
                        continue
            except Exception as e:
                print(f"⚠️ Error fetching user info (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(random.randint(5, 15))
                    continue
        
        return f"user_{user_id}"

    def safe_instagram_login():
        """Login with better error handling and session management"""
        cl = Client()
        SETTINGS_PATH = "insta_session.json"

        cl.delay_range = [3, 6]

        if os.path.exists(SETTINGS_PATH):
            try:
                print("🔄 Loading saved session...")
                cl.load_settings(SETTINGS_PATH)
                cl.login(username, password)
                print("✅ Session loaded successfully")
                return cl
            except Exception as e:
                print(f"⚠️ Failed to load session: {e}")
                print("🔄 Logging in fresh...")

        max_retries = 3
        for attempt in range(max_retries):
            try:
                cl.login(username, password)
                cl.dump_settings(SETTINGS_PATH)
                print("✅ Fresh login successful")
                return cl
            except Exception as e:
                print(f"❌ Login attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 30
                    print(f"⏳ Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                else:
                    raise e

    def get_threads_with_retry(cl, max_retries=3):
        """Get threads with exponential backoff retry"""
        for attempt in range(max_retries):
            try:
                threads = cl.direct_threads(amount=5)
                return threads
            except Exception as e:
                error_msg = str(e).lower()

                if "500" in error_msg or "server" in error_msg:
                    wait_time = (2 ** attempt) * 10 + random.randint(5, 15)
                    print(f"🔄 Instagram server error (attempt {attempt + 1}). Waiting {wait_time}s...")
                    time.sleep(wait_time)
                elif "rate limit" in error_msg or "429" in error_msg:
                    wait_time = 300 + random.randint(60, 180)
                    print(f"⏱️ Rate limited. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    print(f"❌ Unexpected error: {e}")
                    time.sleep(60)

                if attempt == max_retries - 1:
                    raise e

    def send_message_with_retry(cl, message, user_ids, max_retries=3):
        """Send message with retry logic"""
        for attempt in range(max_retries):
            try:
                cl.direct_send(message, user_ids)
                return True
            except Exception as e:
                error_msg = str(e).lower()

                if "500" in error_msg:
                    wait_time = (attempt + 1) * 15
                    print(f"🔄 Send failed (attempt {attempt + 1}). Waiting {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    print(f"❌ Send error: {e}")
                    time.sleep(30)

                if attempt == max_retries - 1:
                    print("❌ Failed to send message after all retries")
                    return False

    try:
        # Initialize Instagram client
        cl = safe_instagram_login()

        # Store already replied message IDs
        seen_messages = set()

        # Adaptive polling intervals
        base_interval = 180
        max_interval = 600
        current_interval = base_interval
        consecutive_errors = 0

        print("🤖 Live Instagram DM bot is now running...")
        print(f"⏱️ Checking for messages every {current_interval} seconds")
        print("💳 Note: Check OpenRouter credits at https://openrouter.ai/settings/credits")

        while bot_running:
            try:
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
                        seen_messages.add(msg_id)
                        message_found = True

                        # Use safe username fetching
                        sender = safe_get_username(cl, message.user_id)

                        print(f"💬 {sender} said: {msg_text}")

                        # Handle log files
                        log_filename = f"{sender}log.txt"
                        if not os.path.exists(log_filename):
                            with open(log_filename, "w") as initial_msg:
                                initial_msg.write("""Hey, are you guys able to handle more clients? 

we are doing a free 14-day service for businesses like yours.
our system sends 150 DMs a day to people likely to need your service.
are you open to that?
""")

                        # Log the incoming message
                        with open(log_filename, "a") as log_file:
                            log_file.write(f"{sender}: {msg_text}\n")

                        if sender == username:
                            print("Skipping own message.")
                            continue

                        if msg_text == "exit":
                            continue

                        # Read conversation log
                        try:
                            with open(log_filename, "r") as log_file:
                                log_content = log_file.read()
                                if len(log_content) > 800:
                                    log_content = "..." + log_content[-800:]
                        except FileNotFoundError:
                            log_content = ""

                        # Generate reply
                        try:
                            reply = chat(msg_text, log_content)
                            print("🤖 Bot:", reply)

                            # Send reply with retry
                            if send_message_with_retry(cl, reply, [message.user_id]):
                                # Log the reply only if sent successfully
                                with open(log_filename, "a") as log_file:
                                    log_file.write(f"Bot: {reply}\n")
                                print("✅ Message sent successfully")
                            else:
                                print("❌ Failed to send message")

                        except Exception as e:
                            print(f"❌ Error generating/sending reply: {e}")

                        # Add delay between processing messages
                        time.sleep(random.randint(10, 20))

                if message_found:
                    print(f"✅ Processed messages. Next check in {current_interval} seconds")
                else:
                    print(f"📭 No new messages. Next check in {current_interval} seconds")

                # Wait before checking again
                time.sleep(current_interval)

            except Exception as e:
                consecutive_errors += 1
                error_msg = str(e).lower()

                if "500" in error_msg:
                    current_interval = min(max_interval, current_interval + 60)
                    wait_time = current_interval + random.randint(30, 120)
                    print(f"🔴 Instagram server issues detected. Waiting {wait_time} seconds...")
                    print(f"📈 Increased polling interval to {current_interval} seconds")
                elif "login" in error_msg or "challenge" in error_msg:
                    print("🔐 Login issue detected. Attempting re-login...")
                    try:
                        cl = safe_instagram_login()
                        wait_time = 60
                    except Exception as login_error:
                        print(f"❌ Re-login failed: {login_error}")
                        wait_time = 600
                else:
                    wait_time = min(300, 30 * consecutive_errors)
                    print(f"⚠️ Error (#{consecutive_errors}): {e}")
                    print(f"⏳ Waiting {wait_time} seconds before retry...")

                time.sleep(wait_time)
                
    except Exception as e:
        print(f"❌ Bot crashed: {e}")
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