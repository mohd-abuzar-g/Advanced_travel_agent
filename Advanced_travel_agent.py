import streamlit as st
import os
import re
import requests
from datetime import datetime, timedelta, date
from typing import Optional
from agno.agent import Agent
from agno.models.openrouter import OpenRouter
from icalendar import Calendar, Event

# --- SETTINGS ---
os.environ["PYTHONIOENCODING"] = "utf-8"
st.set_page_config(
    page_title="Global AI Travel Planner",
    layout="wide",
    page_icon="🗺️",
    initial_sidebar_state="expanded"
)

if 'itinerary' not in st.session_state:
    st.session_state.itinerary = None
if 'full_response' not in st.session_state:
    st.session_state.full_response = ""

# --- SERPER DEV TOOL ---
class SerperDevTool:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.endpoint = "https://google.serper.dev/search"
        self.cache = {}

    def search(self, query: str, retries: int = 2) -> str:
        if query in self.cache:
            return self.cache[query]

        headers = {"X-API-KEY": self.api_key, "Content-Type": "application/json"}
        payload = {"q": query, "num": 3}

        for attempt in range(retries):
            try:
                resp = requests.post(self.endpoint, headers=headers, json=payload, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                snippets = []
                if "organic" in data:
                    for item in data["organic"]:
                        title = item.get("title", "")
                        snippet = item.get("snippet", "")
                        link = item.get("link", "")
                        snippets.append(f"{title}\n{snippet}\n{link}")
                result = "\n\n".join(snippets)
                self.cache[query] = result
                return result
            except Exception as e:
                if attempt == retries - 1:
                    return f"Search failed after {retries} attempts: {e}"
# --- ICS GENERATOR ---
def generate_ics_content(plan_text: str, start_date_input: date, destination: str) -> Optional[bytes]:
    try:
        start_dt = datetime.combine(start_date_input, datetime.min.time())
        cal = Calendar()
        cal.add('prodid', '-//Global AI Travel Planner//')
        cal.add('version', '2.0')

        day_pattern = re.compile(
            r'(?:##\s*)?Day\s*(\d+)[\s–:]*([\s\S]*?)(?=(?:##\s*)?Day\s*\d+|$)',
            re.IGNORECASE
        )
        days = day_pattern.findall(plan_text)

        for d_num, content in days:
            e = Event()
            e.add('summary', f"Day {d_num} in {destination}")
            e.add('description', content.strip())
            e.add('dtstart', (start_dt + timedelta(days=int(d_num)-1)).date())
            e.add('dtend', (start_dt + timedelta(days=int(d_num))).date())
            cal.add_component(e)

        return cal.to_ical()
    except Exception as e:
        st.warning(f"ICS generation failed: {e}")
        return None
# --- SIDEBAR UI ---
st.title("🗺️ Global AI Travel Planner")
with st.sidebar:
    st.header("🔑 Credentials")
    or_key = st.text_input("OpenRouter API Key", type="password").strip()
    serp_key = st.text_input("Serper.dev API Key", type="password").strip()
    st.divider()
    arrival_date = st.date_input("Arrival Date", date.today() + timedelta(days=14))
    travel_style = st.selectbox("Travel Style", ["Balanced", "Luxury", "Budget", "Adventure"])
    search_mode = st.selectbox("Search Mode", ["Always search first", "Smart search (recommended)"])

col1, col2 = st.columns([3, 1])
with col1:
    destination = st.text_input("Destination", placeholder="e.g. Tokyo, Japan")
with col2:
    num_days = st.number_input("Days", 1, 14, 5)

# --- AI SETUP ---
if or_key and serp_key:
    model = OpenRouter(id="google/gemini-2.0-flash-001", api_key=or_key)
    planner_ai = Agent(
        name="GlobalPlannerAI",
        model=model,
        tools=[],
        instructions=[
            "You are an expert travel agent. Provide a full, detailed 2026-specific itinerary.",
            "Include Essential Info, Weather, and Day-by-Day Itinerary in one continuous document.",
            "For each day, give main activities, attractions, hotels, local tips, and cultural notes.",
            "Do NOT give hour-by-hour breakdowns or micro-schedules.",
            "Do NOT include code snippets, API calls, or function calls.",
            "Keep the itinerary concise but informative — slightly more detail than just titles.",
            "Format URLs as plain text; they will be clickable in Streamlit.",
            "Use 'Day 1:', 'Day 2:' etc. for each day."
        ],
        markdown=True
    )
    serp_tool = SerperDevTool(api_key=serp_key)

    # --- GENERATE BUTTON ---
    button_placeholder = st.empty()
    generate_button = button_placeholder.button("🛫 Generate Plan", type="primary")

    if generate_button:
        if not destination:
            st.warning("Enter a destination.")
        else:
            button_placeholder.empty()
            with st.status(f"Planning {destination}...", expanded=True):
                try:
                    # Search results for initial context
                    search_results = ""
                    if search_mode in ["Always search first", "Smart search (recommended)"]:
                        essential_query = f"Weather, visa rules, top attractions for {destination} in 2026"
                        search_results = serp_tool.search(essential_query)

                    # Split days into chunks of 3 days max
                    chunk_size = 3
                    full_itinerary = ""
                    for i, start_day in enumerate(range(1, num_days + 1, chunk_size)):
                        end_day = min(start_day + chunk_size - 1, num_days)

                        if i == 0:
                            # First chunk: include Essential Info + Weather
                            query_chunk = f"Plan Day {start_day} to Day {end_day} of a {num_days}-day {travel_style} trip to {destination} starting {arrival_date}. Include Essential Info and Weather. Use these search results:\n{search_results}"
                        else:
                            # Later chunks: only day-by-day itinerary
                            query_chunk = f"Plan Day {start_day} to Day {end_day} of a {num_days}-day {travel_style} trip to {destination} starting {arrival_date}. Only include Day-by-Day Itinerary, skip Essential Info and Weather."

                        chunk_response = ""
                        for chunk in planner_ai.run(query_chunk, stream=True):
                            if hasattr(chunk, 'content') and chunk.content:
                                chunk_response += chunk.content
                            elif isinstance(chunk, str):
                                chunk_response += chunk
                        full_itinerary += chunk_response + "\n\n"

                    st.session_state.itinerary = full_itinerary
                    st.session_state.full_response = full_itinerary

                except Exception as e:
                    st.error(f"Error during planning: {e}")

# --- DISPLAY FULL ITINERARY ---
def display_full_itinerary(itinerary_text: str):
    lines = itinerary_text.splitlines()
    filtered_lines = [line for line in lines if not line.strip().startswith("getFlightAvailability(")]
    clean_text = "\n".join(filtered_lines)
    clean_text = re.sub(r"(https?://\S+)", r"[\1](\1)", clean_text)
    st.markdown(clean_text)

# --- SHOW ITINERARY & ICS ---
if st.session_state.itinerary:
    st.divider()
    display_full_itinerary(st.session_state.itinerary)
    ics_data = generate_ics_content(st.session_state.itinerary, arrival_date, destination)
    if ics_data:
        st.download_button(
            label="📅 Sync to Calendar",
            data=ics_data,
            file_name=f"{destination.replace(' ', '_')}_trip.ics",
            mime="text/calendar"
        )
