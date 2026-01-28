"""
Baseline Purple Agent - Entry Point.

Demonstrates A2A protocol connectivity with CIRISNode.

Usage:
    python -m tests.purple_agent.run [--url URL] [--api-key KEY] [--scenarios N]
"""

import argparse
import asyncio
import json
import logging
import sys

from tests.purple_agent.client import PurpleAgentClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("purple_agent")


async def main(args):
    logger.info(f"Connecting to CIRISNode at {args.url}")

    async with PurpleAgentClient(
        base_url=args.url,
        api_key=args.api_key,
        jwt_token=args.jwt_token,
    ) as client:

        # Step 1: Discover agent capabilities
        logger.info("=== Step 1: Agent Discovery ===")
        try:
            card = await client.discover_agent()
            logger.info(f"Agent: {card.get('name')}")
            logger.info(f"Version: {card.get('version')}")
            skills = card.get("skills", [])
            for skill in skills:
                logger.info(f"  Skill: {skill.get('name')} - {skill.get('description', '')[:80]}")
        except Exception as e:
            logger.error(f"Agent discovery failed: {e}")
            return

        # Step 2: List available scenarios
        if args.list_scenarios:
            logger.info("=== Step 2: Listing Scenarios ===")
            result = await client.get_scenarios(category=args.category)
            msg = result.get("result", {}).get("message", {})
            parts = msg.get("parts", []) if msg else []
            if parts and parts[0].get("type") == "data":
                data = parts[0]["data"]
                logger.info(f"Available scenarios: {data.get('total', 0)}")
            return

        # Step 3: Run evaluation
        logger.info(f"=== Step 3: Running HE-300 Benchmark ({args.scenarios} scenarios) ===")
        result = await client.run_full_benchmark(
            n_scenarios=args.scenarios,
            category=args.category,
            stream=not args.poll,
        )

        # Step 4: Display results
        logger.info("=== Results ===")
        status = result.get("status", {})
        state = status.get("state", "unknown") if isinstance(status, dict) else status

        if state == "completed":
            # Find evaluation report in artifacts
            for artifact in result.get("artifacts", []):
                if artifact.get("name") == "evaluation_report":
                    for part in artifact.get("parts", []):
                        if part.get("type") == "data":
                            report = part["data"]
                            summary = report.get("summary", {})
                            logger.info(f"Total: {summary.get('total', 0)}")
                            logger.info(f"Correct: {summary.get('correct', 0)}")
                            logger.info(f"Accuracy: {summary.get('accuracy', 0):.2%}")
                            logger.info("By category:")
                            for cat, cat_data in summary.get("by_category", {}).items():
                                logger.info(
                                    f"  {cat}: {cat_data.get('correct', 0)}/{cat_data.get('total', 0)} "
                                    f"({cat_data.get('accuracy', 0):.2%})"
                                )
                            logger.info(f"Duration: {report.get('duration_seconds', 0):.1f}s")
                            logger.info(f"Signature: {report.get('signature', 'N/A')[:32]}...")

                            if args.output:
                                with open(args.output, "w") as f:
                                    json.dump(report, f, indent=2)
                                logger.info(f"Full report saved to {args.output}")
                            return

            logger.info(f"Task completed but no report artifact found")
            logger.info(json.dumps(result, indent=2, default=str))

        elif state == "failed":
            msg = status.get("message", {}) if isinstance(status, dict) else {}
            parts = msg.get("parts", []) if msg else []
            text = parts[0].get("text", "Unknown error") if parts else "Unknown error"
            logger.error(f"Evaluation failed: {text}")

        else:
            logger.warning(f"Unexpected state: {state}")
            logger.info(json.dumps(result, indent=2, default=str))


def cli():
    parser = argparse.ArgumentParser(
        description="CIRISNode Baseline Purple Agent",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="CIRISNode base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key for authentication",
    )
    parser.add_argument(
        "--jwt-token",
        default=None,
        help="JWT token for authentication",
    )
    parser.add_argument(
        "--scenarios",
        type=int,
        default=300,
        help="Number of scenarios to evaluate (default: 300)",
    )
    parser.add_argument(
        "--category",
        default=None,
        choices=["commonsense", "deontology", "justice", "virtue"],
        help="Filter by ethical category",
    )
    parser.add_argument(
        "--poll",
        action="store_true",
        help="Use polling instead of SSE streaming",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List available scenarios and exit",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Save full report to JSON file",
    )

    args = parser.parse_args()
    asyncio.run(main(args))


if __name__ == "__main__":
    cli()
