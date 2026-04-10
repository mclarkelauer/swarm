"""High-level Python API for the inter-agent message bus."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from swarm.messaging.db import init_message_db
from swarm.messaging.models import AgentMessage


class MessageAPI:
    """Persistent message bus backed by SQLite.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn = init_message_db(db_path)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    _SELECT_COLS = (
        "id, from_agent, to_agent, step_id, run_id, "
        "content, message_type, created_at, in_reply_to, read_at"
    )

    @staticmethod
    def _row_to_message(row: tuple[object, ...]) -> AgentMessage:
        return AgentMessage(
            id=str(row[0]),
            from_agent=str(row[1]),
            to_agent=str(row[2]),
            step_id=str(row[3]),
            run_id=str(row[4]),
            content=str(row[5]),
            message_type=str(row[6]),
            created_at=str(row[7]),
            in_reply_to=str(row[8]),
            read_at=str(row[9]),
        )

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def send(
        self,
        from_agent: str,
        to_agent: str,
        content: str,
        step_id: str = "",
        run_id: str = "",
        message_type: str = "response",
    ) -> AgentMessage:
        """Create and persist a message.

        Args:
            from_agent: Agent type of the sender.
            to_agent: Agent type of the receiver (``"*"`` for broadcast).
            content: Message payload (freeform text or JSON string).
            step_id: Optional step ID that produced this message.
            run_id: Plan run identifier.
            message_type: One of ``"request"``, ``"response"``, ``"broadcast"``.

        Returns:
            The persisted ``AgentMessage`` with ``created_at`` filled in.
        """
        msg = AgentMessage.create(
            from_agent=from_agent,
            to_agent=to_agent,
            content=content,
            message_type=message_type,
            step_id=step_id,
            run_id=run_id,
            created_at=datetime.now(tz=UTC).isoformat(),
        )
        self._conn.execute(
            """
            INSERT INTO messages (id, from_agent, to_agent, step_id, run_id,
                                  content, message_type, created_at,
                                  in_reply_to, read_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                msg.id,
                msg.from_agent,
                msg.to_agent,
                msg.step_id,
                msg.run_id,
                msg.content,
                msg.message_type,
                msg.created_at,
                msg.in_reply_to,
                msg.read_at,
            ),
        )
        self._conn.commit()
        return msg

    def receive(
        self,
        agent_name: str,
        run_id: str,
        since: str = "",
        limit: int = 50,
    ) -> list[AgentMessage]:
        """Retrieve messages addressed to *agent_name* in a run.

        Also includes broadcast messages (``to_agent='*'``) for the same run.

        Args:
            agent_name: The receiving agent type.
            run_id: The plan run identifier.
            since: Optional ISO timestamp; only return messages after this time.
            limit: Maximum number of messages to return (newest first).

        Returns:
            List of ``AgentMessage`` ordered by ``created_at`` descending.
        """
        if since:
            rows = self._conn.execute(
                f"""
                SELECT {self._SELECT_COLS}
                FROM messages
                WHERE (to_agent = ? OR to_agent = '*') AND run_id = ?
                  AND created_at > ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (agent_name, run_id, since, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"""
                SELECT {self._SELECT_COLS}
                FROM messages
                WHERE (to_agent = ? OR to_agent = '*') AND run_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (agent_name, run_id, limit),
            ).fetchall()

        return [self._row_to_message(r) for r in rows]

    def broadcast(
        self,
        from_agent: str,
        content: str,
        step_id: str = "",
        run_id: str = "",
    ) -> AgentMessage:
        """Send a broadcast message (``to_agent='*'``) visible to all agents.

        Returns:
            The persisted ``AgentMessage``.
        """
        return self.send(
            from_agent=from_agent,
            to_agent="*",
            content=content,
            message_type="broadcast",
            step_id=step_id,
            run_id=run_id,
        )

    def list_by_run(self, run_id: str) -> list[AgentMessage]:
        """Return all messages for a given run, ordered by creation time.

        Args:
            run_id: The plan run identifier.

        Returns:
            List of ``AgentMessage`` ordered by ``created_at`` ascending.
        """
        rows = self._conn.execute(
            f"""
            SELECT {self._SELECT_COLS}
            FROM messages
            WHERE run_id = ?
            ORDER BY created_at ASC
            """,
            (run_id,),
        ).fetchall()
        return [self._row_to_message(r) for r in rows]

    def list_by_step(self, step_id: str, run_id: str = "") -> list[AgentMessage]:
        """Return all messages produced by a given step.

        Args:
            step_id: The plan step identifier.
            run_id: Optional run_id filter for scoping.

        Returns:
            List of ``AgentMessage`` ordered by ``created_at`` ascending.
        """
        if run_id:
            rows = self._conn.execute(
                f"""
                SELECT {self._SELECT_COLS}
                FROM messages
                WHERE step_id = ? AND run_id = ?
                ORDER BY created_at ASC
                """,
                (step_id, run_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"""
                SELECT {self._SELECT_COLS}
                FROM messages
                WHERE step_id = ?
                ORDER BY created_at ASC
                """,
                (step_id,),
            ).fetchall()
        return [self._row_to_message(r) for r in rows]

    def get_message(self, message_id: str) -> AgentMessage | None:
        """Get a single message by ID.

        Args:
            message_id: The message UUID.

        Returns:
            The message, or None if not found.
        """
        cur = self._conn.execute(
            f"SELECT {self._SELECT_COLS} FROM messages WHERE id = ?",
            (message_id,),
        )
        row = cur.fetchone()
        return self._row_to_message(row) if row else None

    def reply(
        self,
        original_message_id: str,
        from_agent: str,
        content: str,
        *,
        run_id: str = "",
    ) -> AgentMessage:
        """Send a reply to a message, setting in_reply_to for correlation.

        Args:
            original_message_id: ID of the message being replied to.
            from_agent: Name of the replying agent.
            content: Reply content.
            run_id: Plan run identifier.

        Returns:
            The created reply message.
        """
        # Look up original to get sender as recipient
        original = self.get_message(original_message_id)
        to_agent = original.from_agent if original else ""

        msg = AgentMessage(
            id=str(uuid.uuid4()),
            from_agent=from_agent,
            to_agent=to_agent,
            content=content,
            message_type="response",
            run_id=run_id,
            created_at=datetime.now(tz=UTC).isoformat(),
            in_reply_to=original_message_id,
        )
        self._conn.execute(
            "INSERT INTO messages (id, from_agent, to_agent, content, "
            "message_type, run_id, created_at, in_reply_to, read_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                msg.id,
                msg.from_agent,
                msg.to_agent,
                msg.content,
                msg.message_type,
                msg.run_id,
                msg.created_at,
                msg.in_reply_to,
                msg.read_at,
            ),
        )
        self._conn.commit()
        return msg

    def acknowledge(self, message_id: str) -> bool:
        """Mark a message as read/acknowledged.

        Args:
            message_id: The message UUID to acknowledge.

        Returns:
            True if the message was found and acknowledged.
        """
        now = datetime.now(tz=UTC).isoformat()
        cur = self._conn.execute(
            "UPDATE messages SET read_at = ? WHERE id = ? AND read_at = ''",
            (now, message_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get_replies(self, message_id: str) -> list[AgentMessage]:
        """Get all replies to a specific message.

        Args:
            message_id: The original message ID.

        Returns:
            List of reply messages, ordered chronologically.
        """
        cur = self._conn.execute(
            f"SELECT {self._SELECT_COLS} FROM messages "
            "WHERE in_reply_to = ? ORDER BY created_at",
            (message_id,),
        )
        return [self._row_to_message(r) for r in cur.fetchall()]

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
