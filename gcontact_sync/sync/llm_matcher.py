"""
LLM-assisted contact matching for uncertain cases.

Uses Claude or other LLMs to determine if two contacts represent
the same person when deterministic and fuzzy matching are inconclusive.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from gcontact_sync.storage.db import SyncDatabase
    from gcontact_sync.sync.contact import Contact

logger = logging.getLogger(__name__)

# Default LLM configuration
DEFAULT_LLM_MODEL = "claude-haiku-4-5-20250514"
DEFAULT_LLM_MAX_TOKENS = 500
DEFAULT_LLM_BATCH_MAX_TOKENS = 2000


@dataclass
class LLMMatchDecision:
    """Result of LLM matching decision."""

    is_match: bool
    confidence: float  # 0.0 to 1.0
    reasoning: str


class LLMMatcher:
    """
    LLM-based contact matcher for uncertain cases.

    Uses Claude API to analyze contact pairs and determine if they
    represent the same person. Supports caching decisions in a database
    to avoid redundant API calls.

    Usage:
        matcher = LLMMatcher()
        decision = matcher.match_pair(contact1, contact2)
        if decision.is_match:
            print(f"LLM says match: {decision.reasoning}")

        # With caching:
        matcher = LLMMatcher(database=sync_db)
        decision = matcher.match_pair(contact1, contact2)  # Checks cache first
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        database: Optional["SyncDatabase"] = None,
        model: str = DEFAULT_LLM_MODEL,
        max_tokens: int = DEFAULT_LLM_MAX_TOKENS,
        batch_max_tokens: int = DEFAULT_LLM_BATCH_MAX_TOKENS,
    ):
        """
        Initialize the LLM matcher.

        Args:
            api_key: Anthropic API key. If not provided, uses ANTHROPIC_API_KEY env var.
            database: Optional SyncDatabase for caching LLM decisions.
            model: Claude model to use for matching (default: claude-haiku-4-5-20250514)
            max_tokens: Max tokens for single match responses (default: 500)
            batch_max_tokens: Max tokens for batch match responses (default: 2000)
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = None
        self._database = database
        self.model = model
        self.max_tokens = max_tokens
        self.batch_max_tokens = batch_max_tokens

    def _get_client(self):  # type: ignore[no-untyped-def]
        """Lazy-load the Anthropic client. Returns anthropic.Anthropic instance."""
        if self._client is None:
            if not self.api_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY not set. "
                    "Please set it in your environment or pass api_key to LLMMatcher."
                )
            try:
                import anthropic

                self._client = anthropic.Anthropic(api_key=self.api_key)
            except ImportError as err:
                raise ImportError(
                    "anthropic package not installed. Run: uv add anthropic"
                ) from err
        return self._client

    def match_pair(self, contact1: "Contact", contact2: "Contact") -> LLMMatchDecision:
        """
        Use LLM to determine if two contacts are the same person.

        Checks cache first if database is configured. Results are cached
        for future calls with the same contact pair.

        Args:
            contact1: First contact
            contact2: Second contact

        Returns:
            LLMMatchDecision with the match decision and reasoning
        """
        # Check cache first
        if self._database:
            cached = self._get_cached_decision(contact1, contact2)
            if cached:
                logger.debug(
                    f"Using cached LLM decision for {contact1.display_name} <-> "
                    f"{contact2.display_name}"
                )
                return cached

        prompt = self._build_match_prompt(contact1, contact2)

        try:
            client = self._get_client()
            response = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

            decision = self._parse_response(response.content[0].text)

            # Cache the result
            if self._database:
                self._cache_decision(contact1, contact2, decision)

            return decision

        except Exception as e:
            logger.error(f"LLM matching failed: {e}")
            return LLMMatchDecision(
                is_match=False,
                confidence=0.0,
                reasoning=f"LLM matching failed: {e}",
            )

    def match_batch(
        self,
        source_contact: "Contact",
        candidates: list["Contact"],
    ) -> list[tuple["Contact", LLMMatchDecision]]:
        """
        Use LLM to match a source contact against multiple candidates.

        More efficient than calling match_pair repeatedly. Does not use
        caching since batch matching is already optimized.

        Args:
            source_contact: The contact to find matches for
            candidates: List of candidate contacts to check

        Returns:
            List of (contact, decision) tuples for matches found
        """
        if not candidates:
            return []

        prompt = self._build_batch_prompt(source_contact, candidates)

        try:
            client = self._get_client()
            response = client.messages.create(
                model=self.model,
                max_tokens=self.batch_max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

            return self._parse_batch_response(response.content[0].text, candidates)

        except Exception as e:
            logger.error(f"Batch LLM matching failed: {e}")
            return []

    def _build_match_prompt(self, contact1: "Contact", contact2: "Contact") -> str:
        """Build the prompt for matching two contacts."""
        c1_emails = ", ".join(contact1.emails) if contact1.emails else "None"
        c1_phones = ", ".join(contact1.phones) if contact1.phones else "None"
        c1_orgs = (
            ", ".join(contact1.organizations) if contact1.organizations else "None"
        )
        c2_emails = ", ".join(contact2.emails) if contact2.emails else "None"
        c2_phones = ", ".join(contact2.phones) if contact2.phones else "None"
        c2_orgs = (
            ", ".join(contact2.organizations) if contact2.organizations else "None"
        )

        intro = "You are a contact deduplication expert. "
        intro += "Determine if these two contacts represent the same person."

        return f"""{intro}

Contact 1:
- Name: {contact1.display_name}
- Given Name: {contact1.given_name or "N/A"}
- Family Name: {contact1.family_name or "N/A"}
- Emails: {c1_emails}
- Phones: {c1_phones}
- Organizations: {c1_orgs}

Contact 2:
- Name: {contact2.display_name}
- Given Name: {contact2.given_name or "N/A"}
- Family Name: {contact2.family_name or "N/A"}
- Emails: {c2_emails}
- Phones: {c2_phones}
- Organizations: {c2_orgs}

Consider:
1. Name variations (nicknames, middle names, typos)
2. Email domain patterns (personal vs work)
3. Phone number formats
4. Organization context

Respond with ONLY valid JSON (no markdown):
{{"is_match": true/false, "confidence": 0.0-1.0, "reasoning": "brief explanation"}}"""

    def _build_batch_prompt(
        self, source: "Contact", candidates: list["Contact"]
    ) -> str:
        """Build the prompt for batch matching."""
        candidates_text = ""
        for i, c in enumerate(candidates):
            c_emails = ", ".join(c.emails) if c.emails else "None"
            c_phones = ", ".join(c.phones) if c.phones else "None"
            c_orgs = ", ".join(c.organizations) if c.organizations else "None"
            candidates_text += f"""
Candidate {i + 1}:
- Name: {c.display_name}
- Emails: {c_emails}
- Phones: {c_phones}
- Organizations: {c_orgs}
"""

        src_emails = ", ".join(source.emails) if source.emails else "None"
        src_phones = ", ".join(source.phones) if source.phones else "None"
        src_orgs = ", ".join(source.organizations) if source.organizations else "None"

        intro = "You are a contact deduplication expert. "
        intro += "Determine which candidates match the source contact."

        return f"""{intro}

Source Contact:
- Name: {source.display_name}
- Given Name: {source.given_name or "N/A"}
- Family Name: {source.family_name or "N/A"}
- Emails: {src_emails}
- Phones: {src_phones}
- Organizations: {src_orgs}

Candidates to check:
{candidates_text}

Consider name variations, email patterns, phone formats, and organization context.

Respond with ONLY valid JSON (no markdown):
{{"matches": [{{"candidate_index": 1, "confidence": 0.9, "reasoning": "..."}}]}}

Only include candidates that ARE matches. Empty array if no matches."""

    def _parse_response(self, response_text: str) -> LLMMatchDecision:
        """Parse the LLM response for a single match."""
        try:
            # Clean up response if it has markdown code blocks
            text = response_text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            text = text.strip()

            data = json.loads(text)
            return LLMMatchDecision(
                is_match=data.get("is_match", False),
                confidence=float(data.get("confidence", 0.0)),
                reasoning=data.get("reasoning", "No reasoning provided"),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            logger.debug(f"Response was: {response_text}")
            return LLMMatchDecision(
                is_match=False,
                confidence=0.0,
                reasoning=f"Failed to parse LLM response: {e}",
            )

    def _parse_batch_response(
        self, response_text: str, candidates: list["Contact"]
    ) -> list[tuple["Contact", LLMMatchDecision]]:
        """Parse the LLM response for batch matching."""
        try:
            # Clean up response if it has markdown code blocks
            text = response_text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            text = text.strip()

            data = json.loads(text)
            matches = data.get("matches", [])

            results = []
            for match in matches:
                idx = match.get("candidate_index", 0) - 1  # Convert to 0-based
                if 0 <= idx < len(candidates):
                    decision = LLMMatchDecision(
                        is_match=True,
                        confidence=float(match.get("confidence", 0.8)),
                        reasoning=match.get("reasoning", "LLM match"),
                    )
                    results.append((candidates[idx], decision))

            return results

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Failed to parse batch LLM response: {e}")
            logger.debug(f"Response was: {response_text}")
            return []

    # =========================================================================
    # Caching Methods
    # =========================================================================

    def _get_cached_decision(
        self, contact1: "Contact", contact2: "Contact"
    ) -> Optional[LLMMatchDecision]:
        """
        Check if we have a valid cached decision for this contact pair.

        A cached decision is valid only if both contacts' content hashes
        match what was stored. If either contact has changed, the cache
        is invalidated.

        Args:
            contact1: First contact
            contact2: Second contact

        Returns:
            LLMMatchDecision if valid cache exists, None otherwise
        """
        if not self._database:
            return None

        attempt = self._database.get_llm_match_attempt(
            contact1.resource_name, contact2.resource_name
        )
        if not attempt:
            return None

        # Check if contact data changed (invalidates cache)
        stored_hash1 = attempt.get("contact1_content_hash")
        stored_hash2 = attempt.get("contact2_content_hash")
        current_hash1 = contact1.content_hash()
        current_hash2 = contact2.content_hash()

        # Handle both orderings since DB might store (A,B) but we query (B,A)
        hashes_match = (
            stored_hash1 == current_hash1 and stored_hash2 == current_hash2
        ) or (stored_hash1 == current_hash2 and stored_hash2 == current_hash1)

        if not hashes_match:
            logger.debug(
                f"Cache invalidated for {contact1.display_name} <-> "
                f"{contact2.display_name} (contact data changed)"
            )
            return None

        return LLMMatchDecision(
            is_match=bool(attempt["is_match"]),
            confidence=float(attempt["confidence"] or 0.0),
            reasoning=f"(cached) {attempt['reasoning']}",
        )

    def _cache_decision(
        self,
        contact1: "Contact",
        contact2: "Contact",
        decision: LLMMatchDecision,
    ) -> None:
        """
        Store LLM decision in database cache.

        Args:
            contact1: First contact
            contact2: Second contact
            decision: The LLM match decision to cache
        """
        if not self._database:
            return

        try:
            self._database.upsert_llm_match_attempt(
                contact1_resource_name=contact1.resource_name,
                contact2_resource_name=contact2.resource_name,
                contact1_display_name=contact1.display_name,
                contact2_display_name=contact2.display_name,
                contact1_content_hash=contact1.content_hash(),
                contact2_content_hash=contact2.content_hash(),
                is_match=decision.is_match,
                confidence=decision.confidence,
                reasoning=decision.reasoning,
                model_used=self.model,
            )
        except Exception as e:
            logger.warning(f"Failed to cache LLM decision: {e}")
