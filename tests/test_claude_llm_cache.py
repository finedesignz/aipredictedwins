import sys, os, tempfile, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.claude_llm import LLMCache


class TestLLMCache:
    def _db(self, tmp_path):
        return os.path.join(tmp_path, "test_cache.db")

    def test_miss_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(self._db(tmp))
            assert cache.get("hello", "model-x") is None

    def test_put_then_get(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(self._db(tmp))
            cache.put("hello", "model-x", "the response")
            assert cache.get("hello", "model-x") == "the response"

    def test_different_model_is_miss(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(self._db(tmp))
            cache.put("hello", "model-a", "response-a")
            assert cache.get("hello", "model-b") is None

    def test_different_prompt_is_miss(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(self._db(tmp))
            cache.put("prompt-1", "model-x", "resp-1")
            assert cache.get("prompt-2", "model-x") is None

    def test_idempotent_put(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = LLMCache(self._db(tmp))
            cache.put("p", "m", "first")
            cache.put("p", "m", "second")   # should overwrite
            assert cache.get("p", "m") == "second"

    def test_db_created_automatically(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._db(tmp)
            assert not os.path.exists(path)
            LLMCache(path)
            assert os.path.exists(path)
