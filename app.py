from hashlib import sha256
import json
import os
from pathlib import Path
import time
from uuid import uuid4

import pandas as pd
import streamlit as st

from agent import answer_question
from grading import InputError, analyze, export_excel
from storage import save_result


ROOT = Path(__file__).parent
st.set_page_config(page_title="00 학원 평가 도우미", page_icon=str(ROOT / "assets/gachon-logo.png"),
                   layout="wide", initial_sidebar_state="auto")
st.markdown("<style>" + (ROOT / "assets/style.css").read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)


def setting(name, default=""):
    try:
        return st.secrets.get(name, os.getenv(name, default))
    except (FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        return os.getenv(name, default)


def database_config():
    return {k: setting(k) for k in ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY")}


def home():
    left, right = st.columns([1.7, 1], gap="large", vertical_alignment="center")
    with left:
        st.image(str(ROOT / "assets/gachon-logo.png"), width=110)
        st.markdown('<h1 class="landing-title">00 학원 평가 도우미</h1>', unsafe_allow_html=True)
        st.write("문제지·정답지·학생 응답을 올리면 점수와 오답을 분석합니다.\n\n결과를 질문하고, 많이 틀린 유형으로 새 문제를 만들어 보세요.")
        if st.button("채점 시작하기", type="primary", icon=":material/arrow_forward:"):
            st.switch_page(analysis_page)
    with right:
        st.header("준비할 파일은 세 가지")
        for title, detail in [("문제지 PDF", "지문과 선지가 포함된 텍스트 PDF"),
                              ("정답지 PDF", "문항 번호·정답·배점이 포함된 정답표"),
                              ("학생 응답 XLSX", "OMR 인식 결과 · 학생명, Q01~문항 번호")]:
            st.divider()
            st.markdown(f"**{title}**")
            st.write(detail)
    st.divider()
    a, b, c = st.columns(3, gap="large")
    with a:
        st.header("정답표로 자동 채점")
        st.write("업로드한 정답과 배점을 읽어 학생별 점수를 계산합니다.")
    with b:
        st.header("결과를 엑셀로")
        st.write("전체 통계·학생별 정오답·문항별 오답률을 내려받습니다.")
    with c:
        st.header("오답에서 다음 문제로")
        st.write("성적을 대화로 확인하고, 비슷한 유형의 연습문제를 만듭니다.")


def show_message(message):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        exercise = message.get("exercise")
        if exercise:
            st.subheader(exercise["question_type"])
            st.write(exercise["instruction"])
            st.markdown(exercise["passage"])
            for index, choice in enumerate(exercise["choices"], 1):
                st.write(f"{index}. {choice}")
            with st.expander("정답·해설 보기"):
                st.write(f"정답: {exercise['answer']}번")
                st.write(exercise["explanation"])
        if "elapsed" in message:
            label = f"OpenAI · {message['model_used']} · {message['api_calls']}회" if message.get("api_calls") else "AI 답변 미완료"
            st.caption(f"{label} · {message['elapsed']:.1f}초")


def workspace():
    st.session_state.setdefault("session_id", str(uuid4()))
    st.session_state.setdefault("messages", [])
    # 이전 규칙 분기가 잘못 저장한 학생 참조만 초기화하고 대화·채점 결과는 보존한다.
    if st.session_state.get("chat_engine_version") != 3:
        st.session_state.update(chat_engine_version=3, last_student=None)
    with st.sidebar:
        st.image(str(ROOT / "assets/gachon-logo.png"), width=64)
        st.header("시험 파일")
        problem = st.file_uploader("문제지 PDF", type=["pdf"], key="problem_upload")
        key_pdf = st.file_uploader("정답지 PDF", type=["pdf"], key="key_upload")
        responses = st.file_uploader("학생 응답 XLSX", type=["xlsx"], key="responses_upload")
        st.caption("파일당 최대 20MB · 텍스트 PDF · 학생명, Q01~ 형식")
        files = [f.getvalue() for f in (problem, key_pdf, responses) if f is not None]
        fingerprint = tuple(sha256(data).hexdigest() for data in files) if len(files) == 3 else None
        ready = fingerprint is not None
        if st.button("분석 시작", type="primary", disabled=not ready, width="stretch"):
            try:
                with st.status("PDF와 학생 응답을 확인하고 있습니다.", expanded=True) as status:
                    st.write("정답·배점 추출 → 문항 확인 → 학생별 채점")
                    result = analyze(*files)
                    excel = export_excel(result)
                    status.update(label="채점 완료", state="complete", expanded=False)
                st.session_state.update(result=result, excel=excel, problem_pdf=files[0],
                                        fingerprint=fingerprint, messages=[], last_student=None,
                                        exam_id=str(uuid4()), db_status="저장 대기")
                st.session_state.db_status = save_result(result, st.session_state.exam_id,
                    st.session_state.session_id, st.session_state.session_id, database_config())
            except InputError as error:
                st.error(str(error))
            except Exception:
                st.error("분석을 완료하지 못했습니다. 입력 파일을 확인하고 다시 시도해 주세요.")
        current = "result" in st.session_state and ready and fingerprint == st.session_state.get("fingerprint")
        st.download_button("결과 엑셀 다운로드", data=st.session_state.get("excel", b""),
                           file_name="영어시험_채점결과.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           disabled=not current, width="stretch")
        if current:
            st.caption(st.session_state.get("db_status", "저장 대기"))
            if setting("SUPABASE_URL") and st.session_state.get("db_status") != "저장 완료" and st.button("DB 저장 다시 시도", width="stretch"):
                st.session_state.db_status = save_result(st.session_state.result, st.session_state.exam_id,
                    st.session_state.session_id, st.session_state.session_id, database_config())
                st.rerun()
        st.divider()
        st.caption("대화는 현재 세션에서만 유지됩니다. 원본 파일은 DB에 저장하지 않습니다.")

    st.title("00 학원 평가 도우미")
    if not current:
        if "result" in st.session_state:
            st.warning("입력 파일이 변경되었습니다. 분석 시작을 눌러 새 결과를 확정해 주세요.")
        else:
            st.header("시험 파일을 올려주세요")
            st.write("왼쪽 사이드바에서 문제지 PDF, 정답지 PDF, 학생 응답 XLSX를 선택한 뒤 분석을 시작하세요.")
            st.info("채점이 끝나면 결과 엑셀 다운로드와 질문 입력이 활성화됩니다.")
        st.chat_input("채점 완료 후 질문하세요", disabled=True)
        return
    result, summary = st.session_state.result, st.session_state.result["summary"]
    metrics = st.columns(4)
    for col, label, value in zip(metrics, ["채점 학생", "평균", "중앙값", "표준편차"],
            [f"{summary['count']}명", f"{summary['mean']:.2f}점", f"{summary['median']:.2f}점", f"{summary['std']:.2f}점"]):
        col.metric(label, value)
    st.caption(f"총 {len(result['key'])}문항 · {summary['total']}점 만점 · 표준편차는 모집단 기준")
    with st.expander("오답 상위 문항과 학생별 결과"):
        st.dataframe(pd.DataFrame([{"문항": q, "오답 수": summary["wrong"][q],
                                   "오답률": f"{summary['wrong'][q]/summary['count']:.1%}"}
                                  for q in summary["top_wrong"]]), hide_index=True, width="stretch")
        st.dataframe(pd.DataFrame([{"학생명": s["name"], "점수": s["score"]} for s in result["students"]]),
                     hide_index=True, width="stretch")
    st.divider()
    st.header("채점 결과에 질문하세요")
    st.caption("예: 평균과 중앙값 알려줘 · 최저 성적 학생은 누구야? · 최다 오답으로 유사 문제 1개 만들어줘")
    with st.expander("AI 데이터 사용 안내"):
        st.write("모든 채팅 답변은 OpenAI가 최근 대화와 필요한 조회 결과로 작성합니다. 학생 분석에는 해당 학생의 점수·오답·선택 답·정답·문항 지시문이 전달됩니다. 문제 생성에는 문항·정답·PDF 페이지도 전달됩니다. 원본 페이지에는 다른 문항도 포함될 수 있습니다. 생성 문제는 사용 전 정답과 해설을 검토해 주세요.")
    if not setting("OPENAI_API_KEY"):
        st.warning("OpenAI 키가 없어 AI 채팅을 사용할 수 없습니다. 채점과 엑셀 다운로드는 가능합니다.")
    for message in st.session_state.messages:
        show_message(message)
    prompt = st.chat_input("채점 결과를 질문하세요", max_chars=2000)
    if prompt:
        if time.monotonic() - st.session_state.get("last_request", 0) < 3:
            st.warning("잠시 후 다시 질문해 주세요.")
            return
        st.session_state.last_request = time.monotonic()
        history = [{"role": m["role"], "content": m["content"] + (
            "\n생성 문제: " + json.dumps(m["exercise"], ensure_ascii=False) if m.get("exercise") else "")}
            for m in st.session_state.messages[-20:]]
        user_message = {"role": "user", "content": prompt}
        st.session_state.messages.append(user_message)
        show_message(user_message)
        started = time.monotonic()
        with st.spinner("현재 시험에서 답변을 준비하고 있습니다."):
            response = answer_question(prompt, result, st.session_state.problem_pdf, history,
                setting("OPENAI_API_KEY"), setting("OPENAI_MODEL", "gpt-5.4-mini"), st.session_state.get("last_student"))
        st.session_state.last_student = response.get("last_student")
        message = {"role": "assistant", "content": response["answer"], "exercise": response.get("exercise"),
                   "elapsed": time.monotonic() - started, "api_calls": response.get("api_calls", 0),
                   "model_used": response.get("model_used")}
        st.session_state.messages.append(message)
        st.session_state.messages = st.session_state.messages[-40:]
        show_message(message)


home_page = st.Page(home, title="서비스 소개", default=True)
analysis_page = st.Page(workspace, title="채점·분석", url_path="analysis")
if __name__ == "__main__":
    st.navigation([home_page, analysis_page], position="top").run()
