"""Lightweight async notification dispatcher for WBD task routing."""

import logging
from typing import Optional, Dict, Any

import httpx

from cirisnode.config import settings

logger = logging.getLogger(__name__)


async def notify_authority(
    username: str,
    notification_config: Dict[str, Any],
    task_id: int,
    agent_task_id: str,
    domain_hint: Optional[str] = None,
) -> None:
    """Fire-and-forget notifications to an authority about a WBD task assignment."""
    config = notification_config or {}

    # In-app: nothing to do — UI polls /api/v1/wa/tasks filtered by assignment

    # Email notification
    email_cfg = config.get("email", {})
    if email_cfg.get("enabled") and email_cfg.get("address"):
        try:
            await _send_email(
                to=email_cfg["address"],
                subject=f"[CIRISNode] WBD Task #{task_id} assigned to you",
                body=_build_email_body(username, task_id, agent_task_id, domain_hint),
            )
        except Exception:
            logger.exception("Failed to send email notification for task %s", task_id)

    # Discord webhook
    discord_cfg = config.get("discord", {})
    if discord_cfg.get("enabled") and discord_cfg.get("webhook_url"):
        try:
            await _send_discord_webhook(
                webhook_url=discord_cfg["webhook_url"],
                task_id=task_id,
                agent_task_id=agent_task_id,
                domain_hint=domain_hint,
                username=username,
            )
        except Exception:
            logger.exception("Failed to send Discord notification for task %s", task_id)


def _build_email_body(username: str, task_id: int, agent_task_id: str, domain_hint: Optional[str]) -> str:
    domain_line = f"\nDomain: {domain_hint}" if domain_hint else ""
    return (
        f"Hello {username},\n\n"
        f"A new WBD task has been assigned to you for review.\n\n"
        f"Task ID: {task_id}\n"
        f"Agent Task ID: {agent_task_id}{domain_line}\n\n"
        f"Please log in to the CIRISNode Admin UI to review and resolve this task.\n\n"
        f"— CIRISNode"
    )


async def _send_email(to: str, subject: str, body: str) -> None:
    """Send email via SMTP using aiosmtplib if configured."""
    if not settings.SMTP_HOST:
        logger.warning("SMTP_HOST not configured — skipping email to %s", to)
        return

    try:
        import aiosmtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["From"] = settings.SMTP_FROM
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)

        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER or None,
            password=settings.SMTP_PASS or None,
            start_tls=True,
        )
        logger.info("Email sent to %s for subject: %s", to, subject)
    except ImportError:
        logger.warning("aiosmtplib not installed — skipping email notification")
    except Exception:
        logger.exception("Failed to send email to %s", to)
        raise


async def _send_discord_webhook(
    webhook_url: str,
    task_id: int,
    agent_task_id: str,
    domain_hint: Optional[str],
    username: str,
) -> None:
    """POST a Discord webhook with an embed summarizing the WBD task."""
    embed = {
        "title": f"WBD Task #{task_id} Assigned",
        "color": 0xFF6B35,  # Orange
        "fields": [
            {"name": "Task ID", "value": str(task_id), "inline": True},
            {"name": "Agent Task", "value": agent_task_id, "inline": True},
            {"name": "Assigned To", "value": username, "inline": True},
        ],
    }
    if domain_hint:
        embed["fields"].append({"name": "Domain", "value": domain_hint, "inline": True})
    embed["footer"] = {"text": "CIRISNode WBD Router"}

    payload = {"embeds": [embed]}

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(webhook_url, json=payload)
        resp.raise_for_status()
    logger.info("Discord webhook sent for task %s", task_id)
