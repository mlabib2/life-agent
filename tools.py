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
