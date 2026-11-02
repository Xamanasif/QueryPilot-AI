"""Command line: `python -m querypilot init-db | checklist | ask "question" [--tenant acme]`."""

from __future__ import annotations

import argparse
import json

from .agent import Agent
from .config import Settings
from .db import Database
from .diligence import DiligenceReviewer
from .llm import GroqChatModel


def main() -> None:
    parser = argparse.ArgumentParser(prog="querypilot")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="Create and seed the demo database")
    cl = sub.add_parser("checklist", help="Print the diligence checklist for a tenant")
    cl.add_argument("--tenant", default="acme")
    ask = sub.add_parser("ask", help="Ask the agent a question (requires GROQ_API_KEY)")
    ask.add_argument("question")
    ask.add_argument("--tenant", default="acme")
    args = parser.parse_args()

    settings = Settings()
    db = Database(settings.db_path)
    db.seed_demo()

    if args.command == "init-db":
        print(f"Database ready at {db.path}")
    elif args.command == "checklist":
        print(json.dumps(DiligenceReviewer(db).checklist(args.tenant), indent=2))
    else:
        if not settings.groq_api_key:
            parser.error("GROQ_API_KEY is not set")
        llm = GroqChatModel(settings.groq_api_key, settings.model)
        result = Agent(db, llm, settings).run(args.question, args.tenant, principal="cli")
        print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
