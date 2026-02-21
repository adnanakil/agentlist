"""Tool definitions in Gemini function-calling format."""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Main orchestrator tools
# --------------------------------------------------------------------------- #

MAIN_TOOLS: list[dict] = [
    {
        "function_declarations": [
            {
                "name": "delegate",
                "description": (
                    "Delegate a task to a specialist agent. "
                    "Agents: research (web search, news, factual questions), "
                    "texting (send iMessages), "
                    "brainstorm (creative thinking, analysis)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent": {
                            "type": "string",
                            "description": "Agent name: research, texting, brainstorm",
                        },
                        "task": {
                            "type": "string",
                            "description": "Clear description of the task for the agent",
                        },
                        "context": {
                            "type": "string",
                            "description": "Additional context: URLs, phone numbers, background info",
                        },
                    },
                    "required": ["agent", "task"],
                },
            },
            {
                "name": "current_time",
                "description": "Get the current date and time.",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "memory",
                "description": "Remember or recall information. Actions: remember, recall, list.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "remember, recall, or list",
                        },
                        "content": {
                            "type": "string",
                            "description": "What to remember or search for",
                        },
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "web_search",
                "description": (
                    "Quick web search. For thorough research, "
                    "delegate to the research agent instead."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "send_message",
                "description": (
                    "Send an iMessage directly. "
                    "For complex messaging tasks, delegate to the texting agent."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {
                            "type": "string",
                            "description": "Phone number in +1XXXXXXXXXX format",
                        },
                        "text": {
                            "type": "string",
                            "description": "Message text",
                        },
                    },
                    "required": ["to", "text"],
                },
            },
            {
                "name": "contacts",
                "description": (
                    "Manage the current user's contact profile. "
                    "Actions: get (read profile), update (set fields like name, onboarded, "
                    "google_connected, email, notes)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "get or update",
                        },
                        "name": {
                            "type": "string",
                            "description": "User's name (for update)",
                        },
                        "onboarded": {
                            "type": "boolean",
                            "description": "Set to true after onboarding is complete",
                        },
                        "google_connected": {
                            "type": "boolean",
                            "description": "Whether Google is connected",
                        },
                        "email": {
                            "type": "string",
                            "description": "User's email (for update)",
                        },
                        "notes": {
                            "type": "string",
                            "description": "Any notes about the user",
                        },
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "set_reminder",
                "description": (
                    "Set a reminder for a user. HAL will text them when the time comes. "
                    "Can also list or delete reminders."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "create, list, or delete",
                            "enum": ["create", "list", "delete"],
                        },
                        "text": {
                            "type": "string",
                            "description": "The reminder message (for create)",
                        },
                        "due_time": {
                            "type": "string",
                            "description": (
                                "When to send the reminder in ISO format "
                                "(e.g. 2026-02-10T09:00:00). Use current_time first "
                                "if you need to calculate relative times."
                            ),
                        },
                        "recur": {
                            "type": "string",
                            "description": "Optional recurrence: daily, weekly, or monthly",
                        },
                        "reminder_id": {
                            "type": "string",
                            "description": "Reminder ID (for delete)",
                        },
                    },
                    "required": ["action"],
                },
            },
            # --- Stubbed tools (not yet available in cloud) ---
            {
                "name": "google_auth",
                "description": "Google sign-in management. (Not yet available in cloud version.)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "status, start, or wait"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "google_calendar",
                "description": "Access Google Calendar. (Not yet available in cloud version.)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "list_events, create_event, or search_events"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "google_gmail",
                "description": "Access Gmail. (Not yet available in cloud version.)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "list_emails, read_email, or send_email"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "vault",
                "description": "Encrypted credential storage. (Not yet available in cloud version.)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "store, retrieve, delete, or list"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "connect_account",
                "description": "Connect service accounts. (Not yet available in cloud version.)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "start_qr, start_credentials, check_status, or list_services"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "manage_agents",
                "description": "Create/manage custom agents. (Not yet available in cloud version.)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "The action to perform"},
                        "config": {"type": "object", "description": "Configuration object"},
                    },
                    "required": ["action", "config"],
                },
            },
            {
                "name": "resy",
                "description": "Restaurant reservations via Resy. (Not yet available in cloud version.)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "connect, search, book, my_reservations, disconnect"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "events",
                "description": "Event detection tool. (Not yet available in cloud version.)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Event search query"},
                    },
                    "required": ["query"],
                },
            },
        ]
    }
]


# --------------------------------------------------------------------------- #
# Agent-specific tool subsets (Gemini format)
# --------------------------------------------------------------------------- #

def get_agent_tools(tool_names: list[str]) -> list[dict]:
    """Build a Gemini tools array containing only the specified tool names."""
    all_decls = MAIN_TOOLS[0]["function_declarations"]
    filtered = [d for d in all_decls if d["name"] in tool_names]

    # Add web_fetch if needed (agent-only tool, not in main tools)
    if "web_fetch" in tool_names and not any(d["name"] == "web_fetch" for d in filtered):
        filtered.append({
            "name": "web_fetch",
            "description": "Fetch and read the content of a web page URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch",
                    },
                },
                "required": ["url"],
            },
        })

    if not filtered:
        return []

    return [{"function_declarations": filtered}]
