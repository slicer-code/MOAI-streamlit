import streamlit as st
import streamlit.components.v1 as components
import re
import uuid
import pandas as pd

# ────────────────── 말풍선 생성 함수
# 색상 정의
PRIMARY_USER = "#e2f6e8"
PRIMARY_BOT  = "#f6f6f6"

def render_message(
    message: str,
    sender: str = "bot",
    chips: list[str] | None = None,
    key: str | None = None,
) -> str | None:
    """
    - `message` : 표시할 텍스트 (HTML 허용)
    - `sender`  : "user" | "bot"
    - `chips`   : 버튼 형태로 보여 줄 문자열 리스트
    - return    : 사용자가 클릭한 칩(문자열) 또는 None
    """
    # 1) 말풍선 기본 속성
    color = PRIMARY_USER if sender == "user" else PRIMARY_BOT
    align = "right"       if sender == "user" else "left"

    # 개행 꼬리표 제거
    message = str(message).rstrip()

    # 2) 풍선 출력 
    st.markdown(
        f'''<div style="text-align:{align}; margin:6px 0;">
        <p style = "font-size:13px;"></p>
        <span style="background:{color}; padding:10px 14px; border-radius:12px;
        display:inline-block; max-width:80%; font-size:13px; line-height:1.45;
        word-break:break-word; ">{message}</span>
        </div>''',
        unsafe_allow_html=True,
    )

    # 3) 칩 버튼이 있을 경우
    if chips:
        prefix = f"{key or 'chips'}_{abs(hash(message))}"
        clicked = render_chip_buttons(chips, key_prefix=prefix)
        return clicked
    return None

# ────────────────── 칩버튼 생성 함수
def render_chip_buttons(options, key_prefix="chip", selected_value=None):
    def slugify(text):
        return re.sub(r"[^a-zA-Z0-9]+", "-", str(text)).strip("-").lower() or "empty"
    session_key = f"{key_prefix}_selected"
    selected_value = st.session_state.get(session_key)
    
    # 스타일 적용
    st.markdown(f"""
    <style>
    div[data-testid="stHorizontalBlock"]{{
        display:block !important;        
    }}
    button[data-testid="stBaseButton-secondary"] {{
        background-color: white;
        border: 1px solid #e3e8e7;
        border-radius: 20px;
        padding: 6px 14px;
        font-size: 14px;
        cursor: pointer;
        transition: 0.2s ease-in-out;
        margin-bottom: -2px;
        width: 230px;
        text-align:center;
    }}  
    
    button[data-testid="stBaseButton-secondary"]:hover {{
        background-color: #e8f0ef;
        border-color: #009c75;
        color: #009c75;
    }}
    button[data-testid="baseButton-secondary"][disabled]{{
        background-color: white; 
        border-color: #009c75; !important;   
        color: #009c75; !important;                  
    }}         
    </style>
    """, unsafe_allow_html=True)

    
    clicked_val = None

    #cols = st.columns(len(options))
    for idx, opt in enumerate(options):
        if opt is None or (isinstance(opt, float) and pd.isna(opt)) or str(opt).strip()=="":
            continue

        is_selected = (opt == selected_value)
        is_refresh_btn = "다른 여행지 보기" in str(opt)
        disabled = (opt == selected_value) and not is_refresh_btn

        label = f"{opt}" if is_selected else opt

        # stable key
        safe_opt   = slugify(opt)
        stable_key = f"{key_prefix}_{idx}_{safe_opt}"

        if st.button(label, key=stable_key, disabled=disabled):
            clicked_val = opt

    return clicked_val


# ────────────────── 메시지 리플레이 함수
def replay_log(chat_container=None):
    with chat_container:
        for sender, msg in st.session_state.chat_log:
            render_message(msg, sender=sender)


# ────────────────── 메시지 로깅&생성 함수
def log_and_render(msg, sender, chat_container=None, key=None, chips=None):
    # 중복 방지 로직
    sent_once = st.session_state.setdefault("sent_once", {})
    if key and sent_once.get(key):
        return
    if key:
        sent_once[key] = True
    if st.session_state.chat_log and st.session_state.chat_log[-1] == (sender, msg):
        return
    
    # 로그에 저장
    st.session_state.chat_log.append((sender, msg))

    # 메시지 출력
    with chat_container:
        rendered = render_message(msg, sender=sender, chips=chips, key=key)

    return rendered