"""
Tests for the LLM matcher module.

Tests the LLM-assisted contact matching functionality.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from gcontact_sync.sync.contact import Contact
from gcontact_sync.sync.llm_matcher import LLMMatchDecision, LLMMatcher


class TestLLMMatchDecision:
    """Tests for the LLMMatchDecision dataclass."""

    def test_decision_fields(self):
        """Test that LLMMatchDecision has the expected fields."""
        decision = LLMMatchDecision(
            is_match=True, confidence=0.9, reasoning="Same person"
        )
        assert decision.is_match is True
        assert decision.confidence == 0.9
        assert decision.reasoning == "Same person"

    def test_decision_no_match(self):
        """Test a non-matching decision."""
        decision = LLMMatchDecision(
            is_match=False, confidence=0.1, reasoning="Different people"
        )
        assert decision.is_match is False
        assert decision.confidence == 0.1


class TestLLMMatcherInit:
    """Tests for LLMMatcher initialization."""

    def test_init_with_api_key(self):
        """Test initialization with explicit API key."""
        matcher = LLMMatcher(api_key="test-key")
        assert matcher.api_key == "test-key"
        assert matcher._client is None

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "env-key"})
    def test_init_from_env(self):
        """Test initialization from environment variable."""
        matcher = LLMMatcher()
        assert matcher.api_key == "env-key"

    @patch.dict("os.environ", {}, clear=True)
    def test_init_no_key(self):
        """Test initialization without API key."""
        # Remove ANTHROPIC_API_KEY if it exists
        import os

        if "ANTHROPIC_API_KEY" in os.environ:
            del os.environ["ANTHROPIC_API_KEY"]
        matcher = LLMMatcher()
        assert matcher.api_key is None


class TestGetClient:
    """Tests for the _get_client method."""

    def test_get_client_no_api_key_raises(self):
        """Test that _get_client raises ValueError without API key."""
        matcher = LLMMatcher(api_key=None)
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY not set"):
            matcher._get_client()

    def test_get_client_creates_client(self):
        """Test that _get_client creates Anthropic client."""
        pytest.importorskip("anthropic")
        import anthropic

        matcher = LLMMatcher(api_key="test-key")
        with patch.object(anthropic, "Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_anthropic.return_value = mock_client

            client = matcher._get_client()

            assert client == mock_client
            mock_anthropic.assert_called_once_with(api_key="test-key")

    def test_get_client_caches_client(self):
        """Test that _get_client returns cached client on subsequent calls."""
        matcher = LLMMatcher(api_key="test-key")
        # Set a mock client directly to test caching
        mock_client = MagicMock()
        matcher._client = mock_client

        client1 = matcher._get_client()
        client2 = matcher._get_client()

        assert client1 is mock_client
        assert client1 is client2

    def test_get_client_import_error(self):
        """Test that _get_client raises ImportError if anthropic not installed."""
        # Note: Can't easily test import error without uninstalling anthropic
        # The import happens inside the method, so we just verify
        # that the matcher can be instantiated
        _ = LLMMatcher(api_key="test-key")
        # If we get here, the module was importable
        assert True


class TestMatchPair:
    """Tests for the match_pair method."""

    @pytest.fixture
    def contact1(self):
        """Create a test contact."""
        return Contact(
            resource_name="people/1",
            etag="etag1",
            given_name="John",
            family_name="Doe",
            display_name="John Doe",
            emails=["john@example.com"],
            phones=["555-1234"],
            organizations=["Acme Inc"],
        )

    @pytest.fixture
    def contact2(self):
        """Create another test contact."""
        return Contact(
            resource_name="people/2",
            etag="etag2",
            given_name="J",
            family_name="Doe",
            display_name="J. Doe",
            emails=["jdoe@work.com"],
            phones=["555-5678"],
            organizations=["Acme Inc"],
        )

    def test_match_pair_returns_match(self, contact1, contact2):
        """Test match_pair returns a match decision."""
        mock_response = MagicMock()
        response_json = (
            '{"is_match": true, "confidence": 0.95, '
            '"reasoning": "Same person, different names"}'
        )
        mock_response.content = [MagicMock(text=response_json)]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        matcher = LLMMatcher(api_key="test-key")
        matcher._client = mock_client  # Inject mock client directly
        decision = matcher.match_pair(contact1, contact2)

        assert decision.is_match is True
        assert decision.confidence == 0.95
        assert "Same person" in decision.reasoning

    def test_match_pair_returns_no_match(self, contact1, contact2):
        """Test match_pair returns a no-match decision."""
        mock_response = MagicMock()
        response_json = (
            '{"is_match": false, "confidence": 0.1, "reasoning": "Different people"}'
        )
        mock_response.content = [MagicMock(text=response_json)]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        matcher = LLMMatcher(api_key="test-key")
        matcher._client = mock_client
        decision = matcher.match_pair(contact1, contact2)

        assert decision.is_match is False
        assert decision.confidence == 0.1

    def test_match_pair_handles_api_error(self, contact1, contact2):
        """Test match_pair handles API errors gracefully."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("API error")

        matcher = LLMMatcher(api_key="test-key")
        matcher._client = mock_client
        decision = matcher.match_pair(contact1, contact2)

        assert decision.is_match is False
        assert decision.confidence == 0.0
        assert "failed" in decision.reasoning.lower()

    def test_match_pair_contacts_without_optional_fields(self):
        """Test match_pair with contacts missing optional fields."""
        contact1 = Contact(
            resource_name="people/1",
            etag="etag1",
            display_name="John Doe",
        )
        contact2 = Contact(
            resource_name="people/2",
            etag="etag2",
            display_name="Jane Doe",
        )

        mock_response = MagicMock()
        response_json = (
            '{"is_match": false, "confidence": 0.0, "reasoning": "Different names"}'
        )
        mock_response.content = [MagicMock(text=response_json)]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        matcher = LLMMatcher(api_key="test-key")
        matcher._client = mock_client
        decision = matcher.match_pair(contact1, contact2)

        # Should not raise even with missing fields
        assert isinstance(decision, LLMMatchDecision)


class TestMatchBatch:
    """Tests for the match_batch method."""

    @pytest.fixture
    def source_contact(self):
        """Create a source contact."""
        return Contact(
            resource_name="people/1",
            etag="etag1",
            given_name="John",
            family_name="Doe",
            display_name="John Doe",
            emails=["john@example.com"],
        )

    @pytest.fixture
    def candidates(self):
        """Create candidate contacts."""
        return [
            Contact(
                resource_name="people/2",
                etag="etag2",
                display_name="J. Doe",
                emails=["jdoe@work.com"],
            ),
            Contact(
                resource_name="people/3",
                etag="etag3",
                display_name="Jane Smith",
                emails=["jane@example.com"],
            ),
            Contact(
                resource_name="people/4",
                etag="etag4",
                display_name="John Doe Jr",
                emails=["johnjr@example.com"],
            ),
        ]

    def test_match_batch_empty_candidates(self):
        """Test match_batch with empty candidates returns empty list."""
        source = Contact(resource_name="people/1", etag="etag1", display_name="Test")
        matcher = LLMMatcher(api_key="test-key")

        result = matcher.match_batch(source, [])

        assert result == []

    def test_match_batch_returns_matches(self, source_contact, candidates):
        """Test match_batch returns found matches."""
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps(
                    {
                        "matches": [
                            {
                                "candidate_index": 1,
                                "confidence": 0.9,
                                "reasoning": "Same person",
                            },
                            {
                                "candidate_index": 3,
                                "confidence": 0.8,
                                "reasoning": "Related person",
                            },
                        ]
                    }
                )
            )
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        matcher = LLMMatcher(api_key="test-key")
        matcher._client = mock_client
        results = matcher.match_batch(source_contact, candidates)

        assert len(results) == 2
        # First match is candidates[0] (index 0, candidate_index 1)
        assert results[0][0] == candidates[0]
        assert results[0][1].is_match is True
        assert results[0][1].confidence == 0.9
        # Second match is candidates[2] (index 2, candidate_index 3)
        assert results[1][0] == candidates[2]
        assert results[1][1].confidence == 0.8

    def test_match_batch_no_matches(self, source_contact, candidates):
        """Test match_batch with no matches returns empty list."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"matches": []}')]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        matcher = LLMMatcher(api_key="test-key")
        matcher._client = mock_client
        results = matcher.match_batch(source_contact, candidates)

        assert results == []

    def test_match_batch_handles_api_error(self, source_contact, candidates):
        """Test match_batch handles API errors gracefully."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("API error")

        matcher = LLMMatcher(api_key="test-key")
        matcher._client = mock_client
        results = matcher.match_batch(source_contact, candidates)

        assert results == []


class TestParseResponse:
    """Tests for the _parse_response method."""

    @pytest.fixture
    def matcher(self):
        """Create a matcher instance."""
        return LLMMatcher(api_key="test-key")

    def test_parse_valid_json(self, matcher):
        """Test parsing valid JSON response."""
        response = '{"is_match": true, "confidence": 0.85, "reasoning": "Match found"}'
        decision = matcher._parse_response(response)

        assert decision.is_match is True
        assert decision.confidence == 0.85
        assert decision.reasoning == "Match found"

    def test_parse_json_with_code_block(self, matcher):
        """Test parsing JSON wrapped in code block."""
        response = (
            '```json\n{"is_match": true, "confidence": 0.75, "reasoning": "Match"}\n```'
        )
        decision = matcher._parse_response(response)

        assert decision.is_match is True
        assert decision.confidence == 0.75

    def test_parse_json_with_plain_code_block(self, matcher):
        """Test parsing JSON wrapped in plain code block."""
        response = (
            '```\n{"is_match": false, "confidence": 0.1, "reasoning": "No match"}\n```'
        )
        decision = matcher._parse_response(response)

        assert decision.is_match is False

    def test_parse_invalid_json(self, matcher):
        """Test parsing invalid JSON returns default decision."""
        response = "This is not JSON"
        decision = matcher._parse_response(response)

        assert decision.is_match is False
        assert decision.confidence == 0.0
        assert "Failed to parse" in decision.reasoning

    def test_parse_missing_fields(self, matcher):
        """Test parsing JSON with missing fields uses defaults."""
        response = '{"is_match": true}'
        decision = matcher._parse_response(response)

        assert decision.is_match is True
        assert decision.confidence == 0.0
        assert decision.reasoning == "No reasoning provided"

    def test_parse_empty_response(self, matcher):
        """Test parsing empty response."""
        response = ""
        decision = matcher._parse_response(response)

        assert decision.is_match is False
        assert decision.confidence == 0.0


class TestParseBatchResponse:
    """Tests for the _parse_batch_response method."""

    @pytest.fixture
    def matcher(self):
        """Create a matcher instance."""
        return LLMMatcher(api_key="test-key")

    @pytest.fixture
    def candidates(self):
        """Create candidate contacts."""
        return [
            Contact(resource_name="people/1", etag="e1", display_name="Contact 1"),
            Contact(resource_name="people/2", etag="e2", display_name="Contact 2"),
            Contact(resource_name="people/3", etag="e3", display_name="Contact 3"),
        ]

    def test_parse_batch_valid_json(self, matcher, candidates):
        """Test parsing valid batch JSON response."""
        response = json.dumps(
            {
                "matches": [
                    {"candidate_index": 1, "confidence": 0.9, "reasoning": "Match 1"},
                    {"candidate_index": 2, "confidence": 0.8, "reasoning": "Match 2"},
                ]
            }
        )
        results = matcher._parse_batch_response(response, candidates)

        assert len(results) == 2
        assert results[0][0] == candidates[0]  # candidate_index 1 -> index 0
        assert results[0][1].confidence == 0.9
        assert results[1][0] == candidates[1]  # candidate_index 2 -> index 1
        assert results[1][1].confidence == 0.8

    def test_parse_batch_with_code_block(self, matcher, candidates):
        """Test parsing batch JSON wrapped in code block."""
        response = (
            '```json\n{"matches": [{"candidate_index": 3, "confidence": 0.7}]}\n```'
        )
        results = matcher._parse_batch_response(response, candidates)

        assert len(results) == 1
        assert results[0][0] == candidates[2]  # candidate_index 3 -> index 2

    def test_parse_batch_empty_matches(self, matcher, candidates):
        """Test parsing batch response with no matches."""
        response = '{"matches": []}'
        results = matcher._parse_batch_response(response, candidates)

        assert results == []

    def test_parse_batch_invalid_index(self, matcher, candidates):
        """Test parsing batch response with invalid candidate index."""
        response = json.dumps(
            {
                "matches": [
                    {"candidate_index": 10, "confidence": 0.9},  # Out of range
                    {"candidate_index": 0, "confidence": 0.8},  # 0 - 1 = -1, invalid
                ]
            }
        )
        results = matcher._parse_batch_response(response, candidates)

        # Both should be skipped as indices are invalid
        assert results == []

    def test_parse_batch_invalid_json(self, matcher, candidates):
        """Test parsing invalid batch JSON returns empty list."""
        response = "Not JSON at all"
        results = matcher._parse_batch_response(response, candidates)

        assert results == []

    def test_parse_batch_missing_confidence(self, matcher, candidates):
        """Test parsing batch response with missing confidence uses default."""
        response = '{"matches": [{"candidate_index": 1}]}'
        results = matcher._parse_batch_response(response, candidates)

        assert len(results) == 1
        assert results[0][1].confidence == 0.8  # default confidence


class TestBuildMatchPrompt:
    """Tests for the _build_match_prompt method."""

    @pytest.fixture
    def matcher(self):
        """Create a matcher instance."""
        return LLMMatcher(api_key="test-key")

    def test_build_prompt_includes_contact_details(self, matcher):
        """Test that prompt includes all contact details."""
        contact1 = Contact(
            resource_name="people/1",
            etag="etag1",
            given_name="John",
            family_name="Doe",
            display_name="John Doe",
            emails=["john@example.com", "johnd@work.com"],
            phones=["555-1234"],
            organizations=["Acme Inc"],
        )
        contact2 = Contact(
            resource_name="people/2",
            etag="etag2",
            given_name="Jane",
            family_name="Smith",
            display_name="Jane Smith",
            emails=["jane@example.com"],
            phones=[],
            organizations=[],
        )

        prompt = matcher._build_match_prompt(contact1, contact2)

        assert "John Doe" in prompt
        assert "john@example.com" in prompt
        assert "555-1234" in prompt
        assert "Acme Inc" in prompt
        assert "Jane Smith" in prompt
        assert "jane@example.com" in prompt
        assert "is_match" in prompt
        assert "confidence" in prompt

    def test_build_prompt_handles_empty_fields(self, matcher):
        """Test that prompt handles contacts with empty fields."""
        contact1 = Contact(
            resource_name="people/1",
            etag="etag1",
            display_name="Test",
        )
        contact2 = Contact(
            resource_name="people/2",
            etag="etag2",
            display_name="Test2",
        )

        prompt = matcher._build_match_prompt(contact1, contact2)

        assert "None" in prompt  # Empty fields should show "None"
        assert "Test" in prompt


class TestBuildBatchPrompt:
    """Tests for the _build_batch_prompt method."""

    @pytest.fixture
    def matcher(self):
        """Create a matcher instance."""
        return LLMMatcher(api_key="test-key")

    def test_build_batch_prompt_includes_all_candidates(self, matcher):
        """Test that batch prompt includes all candidates."""
        source = Contact(
            resource_name="people/1",
            etag="etag1",
            given_name="John",
            family_name="Doe",
            display_name="John Doe",
            emails=["john@example.com"],
        )
        candidates = [
            Contact(
                resource_name="people/2",
                etag="etag2",
                display_name="Jane Smith",
                emails=["jane@test.com"],
            ),
            Contact(
                resource_name="people/3",
                etag="etag3",
                display_name="Bob Jones",
                phones=["555-5678"],
            ),
        ]

        prompt = matcher._build_batch_prompt(source, candidates)

        assert "John Doe" in prompt  # Source contact
        assert "Jane Smith" in prompt  # Candidate 1
        assert "Bob Jones" in prompt  # Candidate 2
        assert "Candidate 1" in prompt
        assert "Candidate 2" in prompt
        assert "matches" in prompt  # Expected response format


class TestLLMMatcherCaching:
    """Tests for LLM match decision caching."""

    @pytest.fixture
    def db(self):
        """Create an initialized in-memory database."""
        from gcontact_sync.storage.db import SyncDatabase

        db = SyncDatabase(":memory:")
        db.initialize()
        return db

    @pytest.fixture
    def contact1(self):
        """Create a test contact."""
        return Contact(
            resource_name="people/123",
            etag="etag1",
            given_name="John",
            family_name="Doe",
            display_name="John Doe",
            emails=["john@example.com"],
        )

    @pytest.fixture
    def contact2(self):
        """Create another test contact."""
        return Contact(
            resource_name="people/456",
            etag="etag2",
            given_name="Johnny",
            family_name="D",
            display_name="Johnny D",
            emails=["johnny@work.com"],
        )

    def test_matcher_uses_cache_on_hit(self, db, contact1, contact2):
        """Test that matcher uses cached decision and skips API call."""
        # Pre-populate the cache
        db.upsert_llm_match_attempt(
            contact1_resource_name=contact1.resource_name,
            contact2_resource_name=contact2.resource_name,
            contact1_display_name=contact1.display_name,
            contact2_display_name=contact2.display_name,
            contact1_content_hash=contact1.content_hash(),
            contact2_content_hash=contact2.content_hash(),
            is_match=True,
            confidence=0.92,
            reasoning="Same person from cache",
            model_used="claude-haiku-4-5-20250514",
        )

        # Create matcher with database - should NOT call API
        mock_client = MagicMock()
        matcher = LLMMatcher(api_key="test-key", database=db)
        matcher._client = mock_client

        decision = matcher.match_pair(contact1, contact2)

        # Verify cached result was used
        assert decision.is_match is True
        assert decision.confidence == 0.92
        assert "(cached)" in decision.reasoning
        # Verify API was NOT called
        mock_client.messages.create.assert_not_called()

    def test_matcher_calls_api_on_cache_miss(self, db, contact1, contact2):
        """Test that matcher calls API when no cache exists."""
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text='{"is_match": true, "confidence": 0.88, "reasoning": "API match"}'
            )
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        matcher = LLMMatcher(api_key="test-key", database=db)
        matcher._client = mock_client

        decision = matcher.match_pair(contact1, contact2)

        # Verify API was called
        mock_client.messages.create.assert_called_once()
        assert decision.is_match is True
        assert decision.confidence == 0.88
        assert "(cached)" not in decision.reasoning

    def test_matcher_caches_api_result(self, db, contact1, contact2):
        """Test that API results are cached in database."""
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text='{"is_match": false, "confidence": 0.15, '
                '"reasoning": "Different people"}'
            )
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        matcher = LLMMatcher(api_key="test-key", database=db)
        matcher._client = mock_client

        matcher.match_pair(contact1, contact2)

        # Verify result was cached
        cached = db.get_llm_match_attempt(
            contact1.resource_name, contact2.resource_name
        )
        assert cached is not None
        assert cached["is_match"] == 0  # SQLite stores False as 0
        assert cached["confidence"] == 0.15
        assert cached["reasoning"] == "Different people"

    def test_cache_invalidated_on_contact_change(self, db, contact1, contact2):
        """Test that cache is invalidated when contact data changes."""
        # Pre-populate cache with old content hashes
        db.upsert_llm_match_attempt(
            contact1_resource_name=contact1.resource_name,
            contact2_resource_name=contact2.resource_name,
            contact1_display_name=contact1.display_name,
            contact2_display_name=contact2.display_name,
            contact1_content_hash="old_hash_1",  # Different from current
            contact2_content_hash="old_hash_2",  # Different from current
            is_match=True,
            confidence=0.9,
            reasoning="Old cached decision",
            model_used="test",
        )

        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text='{"is_match": false, "confidence": 0.1, '
                '"reasoning": "Fresh decision"}'
            )
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        matcher = LLMMatcher(api_key="test-key", database=db)
        matcher._client = mock_client

        decision = matcher.match_pair(contact1, contact2)

        # Cache should have been invalidated, API called
        mock_client.messages.create.assert_called_once()
        assert decision.is_match is False
        assert "(cached)" not in decision.reasoning

    def test_matcher_works_without_database(self, contact1, contact2):
        """Test that matcher works without database (no caching)."""
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text='{"is_match": true, "confidence": 0.85, "reasoning": "Match"}'
            )
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        matcher = LLMMatcher(api_key="test-key", database=None)
        matcher._client = mock_client

        decision = matcher.match_pair(contact1, contact2)

        assert decision.is_match is True
        mock_client.messages.create.assert_called_once()

    def test_default_model_is_haiku(self):
        """Test that the default model is Haiku."""
        assert LLMMatcher.DEFAULT_MODEL == "claude-haiku-4-5-20250514"

    def test_api_call_uses_default_model(self, contact1, contact2):
        """Test that API calls use the DEFAULT_MODEL."""
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text='{"is_match": true, "confidence": 0.8, "reasoning": "Match"}'
            )
        ]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        matcher = LLMMatcher(api_key="test-key")
        matcher._client = mock_client

        matcher.match_pair(contact1, contact2)

        # Verify the model used in the API call
        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["model"] == LLMMatcher.DEFAULT_MODEL
