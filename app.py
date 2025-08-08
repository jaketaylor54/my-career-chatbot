
import os
import google.generativeai as genai
from flask import Flask, request, jsonify, render_template, session
from dotenv import load_dotenv
import re # Import regex for checking user intent

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
# IMPORTANT: Set a secret key for session management.
# In a real application, generate a strong, random key and keep it secret.
# For local testing, a simple string is fine, but CHANGE THIS FOR DEPLOYMENT.
app.secret_key = os.environ.get('SECRET_KEY', 'default_secret_for_local_dev_only')

# Configure the Gemini API with your API key from environment variable
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Define your HIDDEN, FIXED RECOMMENDATION TEXT
# This is what the AI will be forced to say when asked for recommendations.
# Now includes HTML for better display!
FIXED_RECOMMENDATION_TEXT = """
Based on your input, here are three roles you might explore:
<ol>
    <li><b>Project Manager:</b> Ideal for those who enjoy organizing, leading teams, and overseeing tasks to successful completion.</li>
    <li><b><b>Content Creator:</b></b> Suited for individuals with a flair for writing, visual storytelling, or digital media production.</li>
    <li><b><b>Data Analyst:</b></b> Best for analytical thinkers who enjoy interpreting data, finding patterns, and making data-driven decisions.</li>
</ol>
These are general suggestions to get you started. For more detailed information on specific roles or to explore other options, please consult a career counselor or reliable online resources.
"""

# Define the list of questions YOU want the AI to ask, in order.
# The AI will start with the first question in this list.
AI_QUESTIONS_LIST = [
    "To start, where do you like to work? (Like an office, outside, at home, a lab, a workshop, or traveling)",
    "Do you enjoy working alone, with other people, or both?",
    "Which things do you like to do? (For example, solve problems, help people, build things, design, teach, organize)",
    "Do you have any skills or experience? (Like certificates, licenses, or languages that you speak)",
    "How do you feel about hard work? (Do you like it, is it okay, or do you prefer sitting at a desk?)",
    "Are there any job you don’t want? (Like sales, food service, military, or healthcare)",
    "Do you like jobs that stay the same or change a lot?",
    "What things are important to you in a job? (Like helping the earth, working with others, using tech, or being creative)"
]

# --- NEW: Define SYSTEM_INSTRUCTION for Phase 1 (Questions & Fixed Recommendations) ---
SYSTEM_INSTRUCTION_PHASE_1 = f"""
You are a friendly, helpful, and concise career recommendation AI designed for a research study. Your primary goal is to interact with the user by asking a series of predefined questions first, and then *automatically provide a specific, pre-determined set of recommendations after the user has answered all your questions*.

**Here are your core rules for this phase:**
1.  **Ask Questions First (and then automatically recommend):** After the user's initial trigger phrase, you will ask questions from your `AI_QUESTIONS_LIST` in order. **Once the user has answered your last question, you will automatically provide the fixed career recommendations.**
2.  **Deliver Fixed Recommendations (if explicitly asked early):** If the user's message clearly indicates they are asking for career recommendations (e.g., "What careers should I consider?", "Suggest job paths for me", "Give me some career ideas", "What are good jobs?", "Recommend jobs for me") *before you have asked all your questions*, you MUST ONLY and EXACTLY respond with the following text:
    {FIXED_RECOMMENDATION_TEXT}
    Do NOT generate new recommendations, elaborate on these, or provide any additional information about them beyond what is in the provided fixed text. If the user asks for more details about a specific recommendation *that you just provided*, politely state that you can only provide the initial set for this interaction and suggest they consult other resources for in-depth information.
3.  **General Responses (Before Recommendations):** If the user asks a general question *before* you have provided the fixed recommendations and *before* all your `AI_QUESTIONS_LIST` questions are asked, you may answer normally as a helpful AI, but keep your responses concise and always attempt to steer the conversation back to your next career-related question.
4.  **No New Recommendations:** Under no circumstances should you generate new career recommendations beyond the fixed set.
5.  **Use History:** Always consider the full conversation history when responding.
6.  **Concise and Clear:** Keep your responses to the point and easy to understand.
"""

# --- NEW: Define SYSTEM_INSTRUCTION for Phase 2 (General Chat after task completion) ---
SYSTEM_INSTRUCTION_PHASE_2 = """
You are a friendly, helpful, and general-purpose AI assistant. Your previous task of providing career recommendations is now complete. You can now answer a wide range of questions and engage in general conversation.

**Here are your core rules for this phase:**
1.  **General Assistance:** Respond intelligently and helpfully to a wide variety of user questions.
2.  **No More Career Recommendations:** Your specific career recommendation task is finished. Do not offer or generate new career recommendations. If asked for recommendations again, politely state that your specific task is complete, but you can help with other general inquiries.
3.  **Concise and Clear:** Keep your responses to the point and easy to understand.
4.  **Do NOT summarize your role or ask open-ended "What's on your mind?" questions.** Simply respond to the user's query directly.
5.  **Use History:** Always consider the full conversation history when responding.
"""


# Initialize the generative model
model = genai.GenerativeModel('gemini-1.5-flash')


# Helper function to check if user is asking for the FINAL recommendations
def is_recommendation_request(message):
    keywords = ["recommend", "career", "job", "path", "suggest", "find me", "what should i do", "what are good jobs"]
    pattern = r'\b(?:' + '|'.join(re.escape(k) for k in keywords) + r')\b'
    return re.search(pattern, message.lower()) is not None

# Helper function to detect the initial trigger to start asking questions
def is_start_questions_request(message):
    message_lower = message.lower()
    start_keywords = [
        "ask me some questions", "generate job recommendations for me", "start questions",
        "begin recommendations", "start the process", "begin the process",
        "career questions", "start career questions", "let's begin"
    ]
    for keyword_phrase in start_keywords:
        if keyword_phrase in message_lower:
            return True
    return False


@app.route('/')
def index():
    # Reset session for a new interaction if user lands on index
    session.clear() # Clear any previous session data
    # Initialize session variables for the new chat
    session['chat_history'] = []
    session['ai_question_index'] = 0
    # Add a flag to session to track if recommendations have been given
    session['recommendations_given'] = False
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message')
    if not user_message:
        return jsonify({"response": "No message received."}), 400

    # Get current chat history and AI question index from session
    chat_history = session.get('chat_history', [])
    ai_question_index = session.get('ai_question_index', 0)
    recommendations_given = session.get('recommendations_given', False) # Get the new flag

    ai_response = ""

    # --- REVISED LOGIC FLOW ---

    # Determine which SYSTEM_INSTRUCTION to use for the model call
    current_system_instruction = SYSTEM_INSTRUCTION_PHASE_1
    if recommendations_given: # If recommendations have already been given
        current_system_instruction = SYSTEM_INSTRUCTION_PHASE_2


    # 1. SPECIAL CASE: If it's the very first message AND it contains a trigger to START questions
    if ai_question_index == 0 and is_start_questions_request(user_message):
        ai_response = AI_QUESTIONS_LIST[0] # Ask the first question
        session['ai_question_index'] = 1 # Move to the next question

    # 2. STANDARD CASE: If the user is asking for the FINAL recommendations (after questions or at any point)
    elif is_recommendation_request(user_message):
        ai_response = FIXED_RECOMMENDATION_TEXT
        session['ai_question_index'] = len(AI_QUESTIONS_LIST) + 1 # Mark all questions as "asked"
        session['recommendations_given'] = True # Set the flag

    # 3. AUTOMATIC RECOMMENDATIONS: If all AI's questions have been asked (index is at the end)
    #    and recommendations haven't been given yet (ai_question_index is exactly len(AI_QUESTIONS_LIST))
    #    This condition triggers after the user's response to the *last* question.
    elif ai_question_index == len(AI_QUESTIONS_LIST):
        ai_response = "Thank you for answering my questions! Based on your responses, here are some career recommendations for you:\n\n" + FIXED_RECOMMENDATION_TEXT
        session['ai_question_index'] = len(AI_QUESTIONS_LIST) + 1 # Mark as recommendations given
        session['recommendations_given'] = True # Set the flag

    # 4. STANDARD CASE: If AI still has questions to ask (and user isn't asking for final recs)
    elif ai_question_index < len(AI_QUESTIONS_LIST):
        ai_response = AI_QUESTIONS_LIST[ai_question_index] # Ask the next question
        session['ai_question_index'] = ai_question_index + 1 # Increment index for next turn

    # 5. DEFAULT CASE: Recommendations have been given, and user is asking general questions
    #    OR, if user asks a general question BEFORE recommendations are given (handled by SYSTEM_INSTRUCTION_PHASE_1)
    else:
        try:
            # Construct history for the model
            model_history = []
            for entry in chat_history:
                model_history.append({'role': 'user', 'parts': [entry['user_message']]})
                model_history.append({'role': 'model', 'parts': [entry['ai_response']]})

            convo = model.start_chat(history=model_history)

            # Send the user's latest message with the *appropriate* system instruction
            convo_response = convo.send_message(current_system_instruction + "\n\n" + user_message)

            ai_response = convo_response.text

        except Exception as e:
            print(f"Error calling Gemini API for general response: {e}")
            ai_response = "Sorry, I'm having trouble responding right now. Please try again later."
            # Reset session on error to prevent bad state
            session.clear()
            session['chat_history'] = []
            session['ai_question_index'] = 0
            session['recommendations_given'] = False # Reset flag too

    # Store the full interaction (user message + AI response) in session history
    chat_history.append({'user_message': user_message, 'ai_response': ai_response})
    session['chat_history'] = chat_history

    return jsonify({"response": ai_response})

if __name__ == '__main__':
     app.run()