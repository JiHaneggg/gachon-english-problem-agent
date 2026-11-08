from io import BytesIO
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from test_core import spreadsheet, tool_response, final_response


class AppTests(unittest.TestCase):
    def test_home_and_exercise_render(self):
        code = '''
from app import home, show_message
home()
show_message({"role":"assistant", "content":"새 문제입니다.", "exercise": {
    "question_type":"주제", "instruction":"주제는?", "passage":"A new passage.",
    "choices":["A","B","C","D","E"], "answer":1, "explanation":"해설"}, "elapsed":1.0})
'''
        at = AppTest.from_string(code, default_timeout=20).run()
        self.assertFalse(at.exception)
        self.assertEqual(at.button[0].label, "채점 시작하기")
        self.assertEqual(at.expander[0].label, "정답·해설 보기")
        self.assertTrue(any("00 학원 평가 도우미" in m.value for m in at.markdown))

    def test_upload_grade_chat_and_invalidation(self):
        uploads = {"문제지 PDF": b"problem", "정답지 PDF": b"key", "학생 응답 XLSX": spreadsheet([
            ["학생명", "Q01", "Q02"], ["900학생", 1, 2], ["901학생", None, 1]])}

        def pages(data):
            return ["1 ① 2 2 ② 3"] if data == b"key" else ["1. First question\n2. Second question"]

        with patch("streamlit.file_uploader", side_effect=lambda label, **kw: BytesIO(uploads[label]) if uploads.get(label) else None), \
                patch("grading.pdf_pages", side_effect=pages), patch("storage.create_client"), \
                patch("agent.request", side_effect=[tool_response("get_student_result", {"student_name":"900학생"}),
                    final_response("900학생은 5점입니다.", "900학생"),
                    tool_response("get_student_result", {"student_name":"900학생"}),
                    final_response("901학생은 0점입니다.", "901학생"),
                    tool_response("get_student_result", {"student_name":"900학생"}),
                    final_response("901학생은 0점입니다.", "901학생")]):
            at = AppTest.from_string("from app import workspace\nworkspace()", default_timeout=20)
            at.secrets["OPENAI_API_KEY"] = "test"
            at.session_state["chat_engine_version"] = 2
            at.session_state["last_student"] = "909학생"
            at.session_state["messages"] = [{"role":"user", "content":"903학생 분석해줘"}]
            at.run()
            self.assertFalse(at.exception)
            self.assertIsNone(at.session_state["last_student"])
            self.assertEqual(len(at.session_state["messages"]), 1)
            self.assertFalse(at.button[0].disabled)
            self.assertTrue(at.chat_input[0].disabled)
            at.button[0].click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.metric[0].value, "2명")
            self.assertEqual(at.title[0].value, "00 학원 평가 도우미")
            self.assertFalse(at.chat_input[0].disabled)
            at.chat_input[0].set_value("900번 학생 몇 점이야?").run()
            self.assertIn("5점", at.session_state["messages"][-1]["content"])
            self.assertEqual(at.session_state["messages"][-1]["api_calls"], 2)
            self.assertTrue(any("OpenAI · test-model · 2회" in c.value for c in at.caption))
            at.session_state["last_request"] = 0
            at.chat_input[0].set_value("학생 901은 몇 점이야?").run()
            self.assertIn("901학생은 0점", at.session_state["messages"][-1]["content"])
            self.assertEqual(at.session_state["last_student"], "901학생")
            at.session_state["last_request"] = 0
            at.chat_input[0].set_value("그 학생 점수 다시 알려줘").run()
            self.assertIn("901학생", at.session_state["messages"][-1]["content"])
            uploads["문제지 PDF"] = b"changed"
            at.run()
            self.assertTrue(at.chat_input[0].disabled)
            self.assertTrue(at.warning)
            at.button[0].click().run()
            self.assertEqual(at.session_state["messages"], [])
            uploads.clear()
            at.run()
            self.assertTrue(at.button[0].disabled)
            self.assertTrue(at.chat_input[0].disabled)


if __name__ == "__main__":
    unittest.main()
