import json
import os
from google import genai
from google.genai import types
import streamlit as st
from prompts import SYSTEM_PROMPT
from prompts import WELCOME_MESSAGE_TEMPLATE
from prompts import SUMMARY_REQUEST_PROMPT
from twilio.rest import Client as TwilioClient


def setting(name):
    return st.secrets.get(name) or os.getenv(name)


GEMINI_API_KEY = setting("GEMINI_API_KEY")
TWILIO_ACCOUNT_SID = setting("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = setting("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_FROM = setting("TWILIO_WHATSAPP_FROM")
TWILIO_CONTENT_SID = setting("TWILIO_CONTENT_SID")


@st.cache_resource
def get_gemini_client():
    return genai.Client(api_key=GEMINI_API_KEY)

@st.cache_resource
def get_twilio_client():
    return TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


MODEL_NAME = "gemini-3.8-flash"

def clean_whatsapp_text(text):
    if not text:
        return "No summary available."   
    text=" ".join(text.split())
    return text[:1500] + "..." if len(text)>1500 else text
def render_message(message):
    with st.chat_message(message["role"]):
        if message["kind"] == "text":
            st.write(message["content"])
        elif message["kind"] == "image":
            st.image(message["content"], caption="Uploaded Image", use_container_width=True)
        
def add_message(role, kind, content):
    st.session_state.messages.append({"role": role, "kind": kind, "content": content})
    render_message(st.session_state.messages[-1])

def ask_gemini(parts):
    try:
        return st.session_state.chat.send_message(parts).text
    except Exception as error:
        return f"Sorry, something went wrong: {error}"

def send_whatsapp(to_number, user_name, summary):
    try:
        content_variables=json.dumps(
            {"1": user_name, "2":clean_whatsapp_text(summary)}, ensure_ascii=False
        )
        message = get_twilio_client().messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=f"whatsapp:{to_number}",
            content_sid=TWILIO_CONTENT_SID,
            content_variables=content_variables
        )
        return True, message.sid
    except Exception as error:
        return False, str(error)


st.set_page_config( 
    page_title="MemoryLens AI", 
    page_icon="🧠", 
    layout="centered" 
)

#Step 1: onboarding(username and phone number)

if 'onboarded' not in st.session_state:
    st.title("Welcome to MemoryLens AI! 🧠")
    st.title("Your visual memory, powered by AI.")

    with st.form("onboarding_form"):
        st.write("Please enter your name and phone number to get started.")
        name=st.text_input("Name")
        whatsapp_number=st.text_input(
            "WhatsApp Number (with country code)", 
            placeholder="+91XXXXXXXXXX",
            help="Please enter your WhatsApp number with the country code. For example, +91XXXXXXXXXX for India."
        )
        submitted = st.form_submit_button("Lets go 🚀")
    if submitted:
        if not name.strip() or not whatsapp_number.strip():
            st.warning("Please enter both your name and WhatsApp number.")
        elif not GEMINI_API_KEY:
            st.error("Add GEMINI_API_KEY to Streamlit secrets or an environment variable before starting.")
        else:
            st.session_state.name = name.strip()
            st.session_state.whatsapp_number = whatsapp_number.strip()
            
            #activate my AI
            st.session_state.chat = get_gemini_client().chats.create(
                model=MODEL_NAME,
                config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
            )
            st.session_state.messages = []
            st.session_state.onboarded  = True
            st.rerun()
    st.stop()

#create a chat interface for the user to interact with the AI
header_col, button_col = st.columns([5,2], vertical_alignment="center")

with header_col:
    st.title("MemoryLens AI 🧠")

with button_col:
    send_disabled = len(st.session_state.messages)<=1
    if st.button("Send to WhatsApp", disabled=send_disabled, use_container_width=True):
        if not all((TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM, TWILIO_CONTENT_SID)):
            st.error("Add the Twilio settings to send summaries through WhatsApp.")
            st.stop()
        conversation = []

        for message in st.session_state.messages:
            if message["kind"] == "text":
                conversation.append(
                    f'{message["role"].capitalize()}: {message["content"]}'
                )
            elif message["kind"] == "image":
                conversation.append(
                    f'{message["role"].capitalize()}: Uploaded an image.'
                )

        summary_prompt = (
            f"{SUMMARY_REQUEST_PROMPT}\n\n"
            "Summarize this conversation using only the information below:\n\n"
            + "\n".join(conversation)
        )

        with st.spinner("Summarizing your conversation..."):
            summary = ask_gemini([summary_prompt])

        if summary.startswith("Sorry, something went wrong:"):
            st.error(summary)
        else:
            success, info = send_whatsapp(
                st.session_state.whatsapp_number,
                st.session_state.name,
                summary
            )

            if success:
                st.success("Summary sent to WhatsApp successfully!")
            else:
                st.error(f"Failed to send summary: {info}")

st.caption(f"Logged in as {st.session_state.name} - updates will be sent to {st.session_state.whatsapp_number}")

if not st.session_state.messages:
    add_message("assistant", "text", WELCOME_MESSAGE_TEMPLATE.format(name=st.session_state.name))
else:
    for message in st.session_state.messages:
        render_message(message)

user_input = st.chat_input(
    "Type your message or upload a file here...",
    accept_file=True, 
    file_type=["png", "jpg", "jpeg"]
)

if user_input:
    photo = user_input.files[0] if user_input.files else None
    text = user_input.text
    parts = []
    if photo is not None:
        photo_bytes = photo.getvalue()
        add_message("user", "image", photo_bytes)
        parts.append(
            types.Part.from_bytes(
                data=photo_bytes,
                mime_type=photo.type
            )
        )
    if text:
        add_message("user", "text", text)
        parts.append(text)
    elif photo is not None:
        parts.append("Please analyze the uploaded image.")
    
    with st.spinner("Analyzing..."):
        answer = ask_gemini(parts)
    add_message("assistant", "text", answer)
