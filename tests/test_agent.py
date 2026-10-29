"""可执行测试：覆盖全部验收点 + 异常输入 + 安全场景。

运行：python -m unittest discover -s tests -v
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent.llm import ModelClient
from src.agent.react_loop import MAX_STEPS, run
from src.agent.tools import Tools

DATA = Path(__file__).resolve().parents[1] / "data"


def ask(q, history=None, tools=None):
    tools = tools or Tools()
    model = ModelClient(offline=True)
    return run(q, history=history, model=model, tools=tools), tools


class TestClearAnswer(unittest.TestCase):
    def test_answered_with_quote(self):
        r, _ = ask("年假有多少天")
        self.assertEqual(r.status, "answered")
        self.assertTrue(r.quotes)
        self.assertEqual(r.quotes[0].doc_id, "D03")

    def test_quote_text_supports_answer(self):
        r, _ = ask("年假有多少天")
        self.assertIn(r.quotes[0].text, r.answer)


class TestDocConflict(unittest.TestCase):
    """核心：D01(30天) vs D02(15天) 冲突，不得擅自选一个。"""

    def test_conflict_detected_and_asks_confirmation(self):
        r, _ = ask("报销期限多久")
        self.assertEqual(r.status, "needs_clarification")
        self.assertTrue(r.conflicts)
        doc_ids = {c["doc_id"] for c in r.conflicts[0]["candidates"]}
        self.assertEqual(doc_ids, {"D01", "D02"})
        self.assertTrue(any("确认" in g for g in r.gap))

    def test_conflict_does_not_pick_side(self):
        r, _ = ask("报销期限多久")
        # 不得给出单一答案
        self.assertEqual(r.answer, "")
        # 两个候选都必须展示，且带原文
        for cand in r.conflicts[0]["candidates"]:
            self.assertIn(cand["doc_id"], ("D01", "D02"))
            self.assertTrue(cand["text"])

    def test_single_doc_no_conflict_answers(self):
        """仅 D01 相关（出差场景）时无冲突，可依据 D01 作答。"""
        r, _ = ask("出差回来多久内报销")
        self.assertEqual(r.status, "answered")
        self.assertEqual(r.quotes[0].doc_id, "D01")


class TestOutOfScope(unittest.TestCase):
    def test_not_found_no_answer(self):
        r, _ = ask("食堂几点开饭")
        self.assertEqual(r.status, "not_found")
        self.assertEqual(r.answer, "")
        self.assertEqual(r.quotes, [])
        self.assertTrue(r.gap)

    def test_never_fabricates(self):
        r, _ = ask("食堂几点开饭")
        blob = json.dumps({"a": r.answer, "g": r.gap}, ensure_ascii=False)
        self.assertNotIn("开饭", r.answer)


class TestParaphrase(unittest.TestCase):
    """改写后的相似问题应命中同一文档。"""

    def test_synonym_hits_same_doc(self):
        r1, _ = ask("年假有多少天")
        r2, _ = ask("年假几天")
        self.assertEqual(r1.status, "answered")
        self.assertEqual(r2.status, "answered")
        self.assertEqual(r1.quotes[0].doc_id, r2.quotes[0].doc_id)

    def test_rewritten_conflict_question_still_conflicts(self):
        # 泛化问法（无场景限定）→ 两份制度都命中 → 冲突
        r, _ = ask("费用多久内要报销")
        self.assertEqual(r.status, "needs_clarification")

    def test_scoped_question_answers_with_d01(self):
        # 带"出差"场景限定 → 仅 D01 相关 → 依据 D01 作答（参考实例规定）
        r, _ = ask("出差报销要多久")
        self.assertEqual(r.status, "answered")
        self.assertEqual(r.quotes[0].doc_id, "D01")

    def test_another_paraphrase(self):
        r, _ = ask("退款什么时候到账")
        self.assertEqual(r.status, "answered")
        self.assertEqual(r.quotes[0].doc_id, "D05")


class TestFollowUp(unittest.TestCase):
    """上下文追问：结合历史补全后再检索。"""

    def test_followup_resolves_pronoun(self):
        r, _ = ask("那它的期限呢", history=[{"role": "user", "content": "年假怎么休"}])
        self.assertEqual(r.status, "answered")
        self.assertEqual(r.quotes[0].doc_id, "D03")

    def test_followup_search_uses_history(self):
        r, _ = ask("那它的期限呢", history=[{"role": "user", "content": "年假怎么休"}])
        search = next(s for s in r.trace if s.action == "search_docs")
        # 检索词应包含历史主题词"年假"，而非孤立代词
        self.assertIn("年假", search.args["query"])


class TestToolFailure(unittest.TestCase):
    def test_tool_error_reported(self):
        r, _ = ask("触发故障的提问")
        self.assertEqual(r.status, "tool_error")
        self.assertTrue(r.gap)
        self.assertEqual(r.answer, "")

    def test_retried_once_then_stopped(self):
        r, _ = ask("触发故障的提问")
        searches = [s for s in r.trace if s.action == "search_docs"]
        self.assertEqual(len(searches), 2)  # 1 次初始 + 1 次重试


class TestSafety(unittest.TestCase):
    """安全：无引用作答被拦截；引用必须来自原文。"""

    def test_no_quotes_answer_blocked(self):
        """模型若试图answered但无引用，循环层拦截。"""
        class BadModel:
            mode = "bad"

            def decide(self, s, m):
                return {"action": "finish", "status": "answered",
                        "answer": "报销期限是99天", "quotes": [], "reason": "编造"}

        r = run("报销期限多久", model=BadModel(), tools=Tools())
        self.assertNotEqual(r.status, "answered")
        self.assertIn("拦截", " ".join(r.gap))

    def test_quotes_come_from_documents(self):
        r, tools = ask("年假有多少天")
        for q in r.quotes:
            doc = tools.read_doc(q.doc_id)
            texts = [s["text"] for s in doc["sections"]]
            self.assertIn(q.text, texts)  # 引用必须能在原文里找到

    def test_never_claims_published(self):
        r, _ = ask("报销期限多久")
        blob = json.dumps({"f": r.final}, ensure_ascii=False)
        self.assertNotIn("已发布", blob)


class TestMalformedModelOutput(unittest.TestCase):
    def test_unknown_action_does_not_crash(self):
        class M:
            mode = "bad"

            def decide(self, s, m):
                return {"action": "guess", "args": {}}

        r = run("年假有多少天", model=M(), tools=Tools())
        self.assertEqual(r.status, "incomplete")
        self.assertGreaterEqual(len(r.trace), 2)

    def test_non_dict_does_not_crash(self):
        class M:
            mode = "bad"

            def decide(self, s, m):
                return "not a dict"

        r = run("年假有多少天", model=M(), tools=Tools())
        self.assertEqual(r.status, "incomplete")


class TestStepLimit(unittest.TestCase):
    def test_max_steps_incomplete(self):
        class LoopModel:
            mode = "loop"

            def decide(self, s, m):
                return {"action": "search_docs", "args": {"query": "x"}}

        r = run("年假有多少天", model=LoopModel(), tools=Tools())
        self.assertEqual(r.status, "incomplete")
        self.assertTrue(any("超限" in g for g in r.gap))
        self.assertLessEqual(len([s for s in r.trace if s.action != "abort"]), MAX_STEPS)


class TestDataSwap(unittest.TestCase):
    """审核要点：替换文档内容，答案/动作随之改变。"""

    def test_swapped_content_changes_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shutil.copy(DATA / "synonyms.json", tmp / "synonyms.json")
            docs = json.loads((DATA / "docs.json").read_text(encoding="utf-8"))
            # 把 D03 年假改为 20 天
            for d in docs["docs"]:
                if d["id"] == "D03":
                    d["sections"][0]["text"] = "年假天数：入职满一年可休 20 天。"
            (tmp / "docs.json").write_text(json.dumps(docs, ensure_ascii=False),
                                           encoding="utf-8")
            r, _ = ask("年假有多少天", tools=Tools(data_dir=tmp))
            self.assertEqual(r.status, "answered")
            self.assertIn("20 天", r.quotes[0].text)
            self.assertIn("20 天", r.answer)

    def test_resolved_conflict_changes_status(self):
        """移除 D02 的报销期限条款 → 冲突消失，直接作答。"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shutil.copy(DATA / "synonyms.json", tmp / "synonyms.json")
            docs = json.loads((DATA / "docs.json").read_text(encoding="utf-8"))
            for d in docs["docs"]:
                if d["id"] == "D02":
                    d["sections"] = [s for s in d["sections"]
                                     if s["key"] != "报销期限"]
            (tmp / "docs.json").write_text(json.dumps(docs, ensure_ascii=False),
                                           encoding="utf-8")
            r, _ = ask("报销期限多久", tools=Tools(data_dir=tmp))
            self.assertEqual(r.status, "answered")
            self.assertEqual(r.quotes[0].doc_id, "D01")


if __name__ == "__main__":
    unittest.main()
