"""Uploaded files → validated answers → deterministic scores and Excel."""

from io import BytesIO
import re
from statistics import mean, median, pstdev
from zipfile import ZipFile

import openpyxl
from openpyxl.styles import Font, PatternFill
import pdfplumber


class InputError(ValueError):
    pass


def pdf_pages(data):
    if not data.startswith(b"%PDF-") or len(data) > 20 * 1024 * 1024:
        raise InputError("PDF 형식과 크기를 확인하세요. 파일당 최대 20MB입니다.")
    try:
        with pdfplumber.open(BytesIO(data)) as pdf:
            if not 1 <= len(pdf.pages) <= 30:
                raise InputError("PDF는 1~30쪽이어야 합니다.")
            pages = []
            for page in pdf.pages:
                # shortcut: 2단 수능형 또는 1단 문서, 다른 편집 형식은 추출기 확장 필요.
                left = page.crop((0, 0, page.width / 2, page.height)).extract_text() or ""
                right = page.crop((page.width / 2, 0, page.width, page.height)).extract_text() or ""
                split = re.search(r"^\s*\d{1,3}\.\s", right, re.M)
                pages.append((left + "\n" + right) if split else (page.extract_text() or ""))
            if not all(text.strip() for text in pages):
                raise InputError("텍스트 없는 PDF입니다. 텍스트가 포함된 원본 PDF를 올려주세요.")
            return pages
    except InputError:
        raise
    except Exception:
        raise InputError("PDF를 읽을 수 없습니다. 암호화·손상 여부를 확인하세요.") from None


def extract_key(data):
    rows = re.findall(r"(?<!\d)(\d{1,3})\s+([①②③④⑤1-5])\s+(\d{1,2})(?=\s|$)",
                      "\n".join(pdf_pages(data)))
    key = {}
    for number, answer, points in rows:
        q, points = int(number), int(points)
        if q in key:
            raise InputError(f"정답 PDF에 {q}번이 중복되어 있습니다.")
        if not 1 <= points <= 20:
            raise InputError(f"{q}번 배점이 올바르지 않습니다.")
        key[q] = {"answer": normalize_answer(answer), "points": points}
    if not key or set(key) != set(range(1, len(key) + 1)):
        raise InputError("정답 PDF의 문항 번호·정답·배점을 모두 읽지 못했습니다. 표 형식을 확인하세요.")
    return dict(sorted(key.items()))


def extract_questions(data, numbers):
    questions, current, group, shared = {}, None, None, []
    shared_pages = set()
    for page_no, text in enumerate(pdf_pages(data)):
        for line in text.splitlines():
            group_match = re.match(r"^\s*\[(\d+)[～~∼–-](\d+)\]", line)
            start = re.match(r"^\s*(\d{1,3})\.\s*(.*)", line)
            if group_match:
                group = tuple(map(int, group_match.groups()))
                shared, shared_pages, current = [line], {page_no}, None
            elif start:
                q = int(start[1])
                if q not in numbers:
                    current = None
                    continue
                if q in questions:
                    raise InputError(f"문제 PDF에 {q}번이 중복 인식되었습니다.")
                in_group = group and group[0] <= q <= group[1]
                questions[q] = {"text": "\n".join(shared + [line]) if in_group else line,
                                "pages": sorted(shared_pages | {page_no}) if in_group else [page_no]}
                current = q
            elif current:
                questions[current]["text"] += "\n" + line
                questions[current]["pages"] = sorted(set(questions[current]["pages"]) | {page_no})
            elif group:
                shared.append(line)
                shared_pages.add(page_no)
    missing = sorted(set(numbers) - questions.keys())
    if missing:
        raise InputError(f"문제 PDF에서 문항을 찾지 못했습니다: {missing}. 텍스트·2단 편집 형식을 확인하세요.")
    return questions


def normalize_answer(value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise InputError("답안은 1~5 또는 빈 셀이어야 합니다.")
    if isinstance(value, str):
        value = value.strip()
        if value in "①②③④⑤" and len(value) == 1:
            return "①②③④⑤".index(value) + 1
        if value in ("1", "2", "3", "4", "5"):
            return int(value)
    if isinstance(value, (int, float)) and value in (1, 2, 3, 4, 5):
        return int(value)
    raise InputError("답안은 1~5 또는 빈 셀이어야 합니다.")


def read_students(data, key):
    if len(data) > 20 * 1024 * 1024:
        raise InputError("학생 엑셀은 최대 20MB입니다.")
    try:
        with ZipFile(BytesIO(data)) as archive:
            if sum(f.file_size for f in archive.infolist()) > 50 * 1024 * 1024:
                raise InputError("압축 해제된 엑셀 크기가 너무 큽니다.")
        wb = openpyxl.load_workbook(BytesIO(data), read_only=True, data_only=False)
    except InputError:
        raise
    except Exception:
        raise InputError("XLSX 파일을 읽을 수 없습니다. 파일 형식을 확인하세요.") from None
    try:
        ws = wb["OMR_응답"] if "OMR_응답" in wb.sheetnames else wb.active
        if ws.max_row > 5001 or ws.max_column > 201:
            raise InputError("학생은 최대 5,000명, 문항은 최대 200개입니다.")
        rows = iter(ws.values)
        headers = next(rows, ())
        if not headers or headers[0] != "학생명":
            raise InputError("첫 열 이름은 '학생명'이어야 합니다.")
        columns = {}
        for col, header in enumerate(headers[1:], 1):
            if header is None:
                continue
            match = re.fullmatch(r"Q(\d{1,3})", str(header).strip(), re.I)
            if not match or int(match[1]) in columns:
                raise InputError("문항 열은 중복 없는 Q01, Q02 등의 이름이어야 합니다.")
            columns[int(match[1])] = col
        if columns.keys() != key.keys():
            raise InputError("학생 엑셀 문항과 정답 PDF의 문항 번호가 일치하지 않습니다.")
        students, names = [], set()
        for row_no, row in enumerate(rows, 2):
            if all(v is None or v == "" for v in row):
                continue
            if any(isinstance(v, str) and v.startswith("=") for v in row):
                raise InputError(f"{row_no}행에 수식이 있습니다. 값으로 바꿔주세요.")
            name = str(row[0]).strip() if row[0] is not None else ""
            if not name or len(name) > 100 or name in names:
                raise InputError(f"{row_no}행 학생명이 없거나, 중복되거나, 100자를 초과했습니다.")
            names.add(name)
            try:
                answers = {q: normalize_answer(row[col]) for q, col in columns.items()}
            except InputError:
                raise InputError(f"{row_no}행 답안이 올바르지 않습니다. 1~5 또는 빈 셀만 허용합니다.") from None
            students.append({"name": name, "answers": answers})
        if not students:
            raise InputError("학생 응답이 없습니다.")
        return students
    finally:
        wb.close()


def grade(key, students):
    results = []
    for student in students:
        correct = {q: student["answers"][q] == item["answer"] for q, item in key.items()}
        score = sum(key[q]["points"] for q in key if correct[q])
        results.append({**student, "correct": correct, "score": score})
    scores = [s["score"] for s in results]
    wrong = {q: sum(not s["correct"][q] for s in results) for q in key}
    return {"key": key, "students": results, "summary": {
        "count": len(results), "total": sum(k["points"] for k in key.values()),
        "mean": mean(scores), "median": median(scores), "std": pstdev(scores),
        "min": min(scores), "max": max(scores),
        "top_wrong": sorted(wrong, key=lambda q: (-wrong[q], q))[:3], "wrong": wrong}}


def analyze(problem_pdf, key_pdf, responses_xlsx):
    key = extract_key(key_pdf)
    students = read_students(responses_xlsx, key)
    questions = extract_questions(problem_pdf, key)
    return {**grade(key, students), "questions": questions}


def export_excel(result):
    wb = openpyxl.Workbook()
    overview = wb.active
    overview.title = "전체 개요"
    summary, key = result["summary"], result["key"]
    for row in [("지표", "값"), ("학생 수", summary["count"]), ("총 배점", summary["total"]),
                ("평균", summary["mean"]), ("중앙값", summary["median"]),
                ("표준편차 (모집단)", summary["std"]), (), ("오답 상위 문항", "오답 수", "오답률")]:
        overview.append(row)
    for q in summary["top_wrong"]:
        overview.append((q, summary["wrong"][q], summary["wrong"][q] / summary["count"]))
        overview.cell(overview.max_row, 3).number_format = "0.0%"
    detail = wb.create_sheet("학생별 결과")
    detail.append(["학생명", "총점"] + [f"Q{q:02}" for q in key])
    for student in result["students"]:
        detail.append([student["name"], student["score"]] + [
            "미응답" if student["answers"][q] is None else ("O" if student["correct"][q] else "X")
            for q in key])
        detail.cell(detail.max_row, 1).data_type = "s"
    items = wb.create_sheet("문항별 분석")
    items.append(["문항", "정답", "배점", "정답 수", "오답 수", "오답률"])
    for q, item in key.items():
        wrong = summary["wrong"][q]
        items.append([q, item["answer"], item["points"], summary["count"] - wrong,
                      wrong, wrong / summary["count"]])
        items.cell(items.max_row, 6).number_format = "0.0%"
    for ws in wb:
        ws.freeze_panes = "B2"
        ws.auto_filter.ref = ws.dimensions
        ws.row_dimensions[1].height = 28
        for cell in ws[1]:
            cell.fill = PatternFill("solid", fgColor="1A1A1A")
            cell.font = Font(color="FFFFFF", bold=True)
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = 22 if col[0].column == 1 else 14
    for row in range(4, 7):
        overview.cell(row, 2).number_format = "0.00"
    output = BytesIO()
    wb.save(output)
    return output.getvalue()
