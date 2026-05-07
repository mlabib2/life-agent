from datetime import date
from tavily import TavilyClient
from config import settings
from db import write_log

TOOLS = [
    {
        "name": "log_data",
        "description": (
            "Log structured data to the database when Mahir reports an activity, "
            "habit, mood, meal, spend, workout, or any other trackable event. "
            "Always call this when Mahir reports something — do not just acknowledge it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "description": "Category of log. One of: habit, mood, food, finance, study, sleep, social, reflection, health_metric, strava_activity",
                },
                "data": {
                    "type": "object",
                    "description": "Structured data for this log entry. Include all relevant fields e.g. {name: gym, duration_min: 60} or {amount: 200, category: groceries}",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional freeform notes to attach to this log entry",
                },
                "date": {
                    "type": "string",
                    "description": "Date of the activity in YYYY-MM-DD format. Defaults to today if not specified.",
                },
            },
            "required": ["type", "data"],
        },
    },
    {
        "name": "search_web",
        "description": (
            "Search the web for current information. Use this when Mahir asks about "
            "something that requires up-to-date data: prices, research, news, recommendations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to send to Tavily",
                },
            },
            "required": ["query"],
        },
    },
]


def handle_tool_call(tool_name: str, tool_input: dict, user_id: int) -> str:
    if tool_name == "log_data":
        log_date = date.fromisoformat(tool_input["date"]) if tool_input.get("date") else date.today()
        write_log(
            user_id=user_id,
            log_type=tool_input["type"],
            data=tool_input["data"],
            notes=tool_input.get("notes", ""),
            log_date=log_date,
        )
        return f"Logged: {tool_input['type']} — {tool_input['data']}"

    if tool_name == "search_web":
        client = TavilyClient(api_key=settings.tavily_api_key)
        response = client.search(tool_input["query"], max_results=5)
        results = response.get("results", [])
        formatted = "\n\n".join(
            f"**{r['title']}**\n{r['content']}\nSource: {r['url']}"
            for r in results
        )
        return formatted or "No results found."

    return f"Unknown tool: {tool_name}"
