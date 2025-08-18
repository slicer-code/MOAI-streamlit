import pandas as pd
import json
import os
import random
from chat_a import (#함수 추가 적용##########
    analyze_emotion,
    detect_intent,
    extract_themes,
    recommend_places_by_theme,
    detect_location_filter,
    generate_intro_message,
    theme_ui_map,
    ui_to_theme_map,
    theme_opening_lines,
    intent_opening_lines,
    apply_weighted_score_filter,
    get_highlight_message,
    get_weather_message,
    get_intent_intro_message,
    recommend_packages,
    handle_selected_place,
    generate_region_intro,
    parse_companion_and_age,
    filter_packages_by_companion_age,
    make_top2_description_custom,
    format_summary_tags_custom,
    make_companion_age_message
)
import streamlit as st
from streamlit.components.v1 import html
from css import render_message, render_chip_buttons, log_and_render, replay_log

import streamlit as st, pandas as pd, requests, json

st.success("🎉 앱이 성공적으로 시작되었습니다! 라이브러리 설치 성공!")

@st.cache_data(show_spinner=False)
def load_csv_any(p):
    return pd.read_csv(p) if str(p).startswith(("http://","https://")) else pd.read_csv(p)

# 데이터 로딩을 위한 함수
@st.cache_data
def load_travel_data(file_path):
    print(f"Caching {file_path}...") # 캐시가 언제 실행되는지 확인용
    return pd.read_csv(file_path)

@st.cache_data
def load_json_data(file_path):
    print(f"Caching {file_path}...")
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

# ───────────────────────────────────── 데이터 로드
trip_url = st.secrets.get("TRIPDATA_URL")
if not trip_url:
    st.error("TRIPDATA_URL 미설정: Streamlit Secrets에 URL을 넣어주세요.")
    st.stop()

travel_df = load_csv_any(trip_url)
external_score_df = load_travel_data("클러스터_포함_외부요인_종합점수_결과_최종.csv")
festival_df = load_travel_data("전처리_통합지역축제.csv")
weather_df = load_travel_data("전처리_날씨_통합_07_08.csv")
package_df = load_travel_data("모두투어_컬럼별_개수_07_08.csv")
master_df = load_travel_data("나라_도시_리스트.csv")
theme_title_phrases = load_json_data("theme_title_phrases.json")

# ───────────────────────────────────── streamlit용 함수
def init_session():
    if "chat_log" not in st.session_state:
        st.session_state.chat_log = []
    if "mode" not in st.session_state:
        st.session_state.mode = None
    if "user_input" not in st.session_state:
        st.session_state.user_input = ""
    if "selected_theme" not in st.session_state:
        st.session_state.selected_theme = None

def make_key(row) -> tuple[str, str]:
    """prev 에 넣고 꺼낼 때 쓰는 고유키(여행지, 여행도시)"""
    return (row["여행지"], row["여행도시"])




# ── P 글꼴 크기 14 px ───────────────────────────────────
st.markdown("""
<style>
/* 기본 p 태그 글꼴 크기 */
html, body, p {
    font-size: 14px !important;   /* ← 14 px 고정 */
    line-height: 1.5;            /* (선택) 가독성을 위한 줄간격 */
}

/* Streamlit 기본 마진 제거로 불필요한 여백 방지 (선택) */
p {
    margin-top: 0;
    margin-bottom: 0.5rem;
}
</style>
""", unsafe_allow_html=True)

# ───────────────────────────────────── region mode
def region_ui(travel_df, external_score_df, festival_df, weather_df, package_df,
              country_filter, city_filter, chat_container, log_and_render):
    """region 모드(특정 나라, 도시를 직접 언급했을 경우) 전용 UI & 로직"""

    # ────────────────── 세션 키 정의
    region_key = "region_chip_selected"
    prev_key   = "region_prev_recommended"
    step_key = "region_step" 
    sample_key = "region_sample_df"

    # ────────────────── 0) 초기화
    if step_key not in st.session_state:
        st.session_state[step_key] = "recommend"
        st.session_state[prev_key]  = set()
        st.session_state.pop(sample_key, None)


    # ────────────────── 1) restart 상태면 인트로만 출력하고 종료
    if st.session_state[step_key] == "restart":
        log_and_render(
            "다시 여행지를 추천해드릴게요!<br>요즘 떠오르는 여행이 있으신가요?",
            sender="bot",
            chat_container=chat_container,
            key="region_restart_intro"
        )
        return
    
    # ────────────────── 2) 추천 단계
    if st.session_state[step_key] == "recommend":

        # 2.1) 추천 문구 출력 (도시 또는 국가 기준)
        city_exists = bool(city_filter) and city_filter in travel_df["여행도시"].values
        country_exists = bool(country_filter) and country_filter in travel_df["여행나라"].values

        # 존재하지 않는 도시인 경우
        if city_filter and not city_exists:
            intro = generate_region_intro('', country_filter)
            log_and_render(
                f"죄송해요. {city_filter}의 여행지는 아직 미정이에요.<br>하지만, {intro}",
                sender="bot",
                chat_container=chat_container,
                key="region_intro_invalid"
            )
        else:
            # 정상적인 도시/국가일 경우
            intro = generate_region_intro(city_filter, country_filter)
            log_and_render(intro, 
                            sender="bot",
                            chat_container=chat_container,
                            key="region_intro")

        # 2.2) 여행지 후보 목록 필터링
        df = travel_df.drop_duplicates(subset=["여행지"])
        if city_exists:
            df = df[df["여행도시"].str.contains(city_filter, na=False)]
        elif country_exists:
            df = df[df["여행나라"].str.contains(country_filter, na=False)]

        # 2.3) 이전 추천 목록과 겹치지 않는 여행지만 남김
        prev = st.session_state.setdefault(prev_key, set())
        remaining = df[~df.apply(lambda r: make_key(r) in prev, axis=1)]
        
        # 추천 가능한 여행지가 없다면 종료 단계로 전환
        if remaining.empty and sample_key not in st.session_state:
            st.session_state[step_key] = "recommand_end"
            st.rerun()
            return
        
        
        # 2.4) 샘플링 (이전 샘플이 없거나 비어 있으면 새로 추출)
        if sample_key not in st.session_state or st.session_state[sample_key].empty:
            sampled = remaining.sample(
                n=min(3, len(remaining)), #최대 3개
                random_state=random.randint(1, 9999)
            )
            st.session_state[sample_key] = sampled

            # tuple 형태로 한꺼번에 추가
            prev.update([make_key(r) for _, r in sampled.iterrows()])
            st.session_state[prev_key] = prev
        else:
            sampled = st.session_state[sample_key]

        loc_df = st.session_state[sample_key]

        # 2.5) 추천 리스트 출력 & 칩 UI
        message = (
            "📌 추천 여행지 목록<br>가장 가고 싶은 곳을 골라주세요!<br><br>" +
            "<br>".join([
                f"{i+1}. <strong>{row.여행지}</strong> "
                f"({row.여행나라}, {row.여행도시}) "
                f"{getattr(row, '한줄설명', '설명이 없습니다')}"
                for i, row in enumerate(loc_df.itertuples())
            ])
        )
        with chat_container:
            log_and_render(message, 
                            sender="bot",
                            chat_container=chat_container, 
                            key=f"region_recommendation_{random.randint(1,999999)}"
                            )
            # 칩 버튼으로 추천지 중 선택받기
            prev_choice = st.session_state.get(region_key, None)
            choice = render_chip_buttons(
                loc_df["여행지"].tolist() + ["다른 여행지 보기 🔄"],
                key_prefix="region_chip",
                selected_value=prev_choice
            )
            
        # 2.7) 선택 결과 처리
        if not choice or choice == prev_choice:
            return
        
        if choice == "다른 여행지 보기 🔄":
            log_and_render("다른 여행지 보기 🔄", 
                   sender="user", 
                   chat_container=chat_container, 
                   key=f"user_place_refresh_{random.randint(1,999999)}")
            
            st.session_state.pop(sample_key, None)
            st.rerun()
            return
        
        # 2.8) 여행지 선택 완료 
        st.session_state[region_key] = choice
        st.session_state[step_key]   = "detail"
        st.session_state.chat_log.append(("user", choice))


        # 실제로 선택된 여행지만 prev에 기록
        match = sampled[sampled["여행지"] == choice]
        if not match.empty:
            prev.add(make_key(match.iloc[0]))
            st.session_state[prev_key] = prev

        # 샘플 폐기
        st.session_state.pop(sample_key, None)
        st.rerun()
        return

    # ────────────────── 3) 추천 종료 단계: 더 이상 추천할 여행지가 없을 때
    elif st.session_state[step_key] == "recommand_end":
        with chat_container:
            # 3.1) 메시지 출력
            log_and_render(
                "⚠️ 더 이상 새로운 여행지가 없어요.<br>다시 질문하시겠어요?",
                sender="bot",
                chat_container=chat_container,
                key="region_empty"
            )
            # 3.2) 재시작 여부 칩 버튼 출력
            restart_done_key = "region_restart_done"
            chip_ph = st.empty() 

            if not st.session_state.get(restart_done_key, False):
                with chip_ph:
                    choice = render_chip_buttons( 
                        ["예 🔄", "아니오 ❌"],
                        key_prefix="region_restart"
                    )
            else:
                choice = None

            # 3.3) 아직 아무것도 선택하지 않은 경우
            if choice is None:
                return
            
            chip_ph.empty()  
            st.session_state[restart_done_key] = True

            # 3.4) 사용자 선택값 출력
            log_and_render(
                choice,
                sender="user",
                chat_container=chat_container,
                key=f"user_restart_choice_{choice}"
            )
                    
            # 3.5) 사용자가 재추천을 원하는 경우   
            if choice == "예 🔄":
                # 여행 추천 상태 초기화
                for k in [region_key, prev_key, sample_key, restart_done_key]:
                    st.session_state.pop(k, None)
                chip_ph.empty()  

                # 다음 추천 단계로 초기화
                st.session_state["user_input_rendered"] = False
                st.session_state["region_step"] = "restart"

                log_and_render(
                    "다시 여행지를 추천해드릴게요!<br>요즘 떠오르는 여행이 있으신가요?",
                    sender="bot",
                    chat_container=chat_container,
                    key="region_restart_intro"
                )
                return
            
            # 3.6) 사용자가 종료를 선택한 경우
            else:
                log_and_render("여행 추천을 종료할게요. 필요하실 때 언제든지 또 찾아주세요! ✈️", 
                               sender="bot", 
                               chat_container=chat_container,
                               key="region_exit")
                st.stop()
            return

    
    # ────────────────── 4) 여행지 상세 단계
    if st.session_state[step_key] == "detail":
        chosen = st.session_state[region_key]
        # city 이름 뽑아서 세션에 저장
        row = travel_df[travel_df["여행지"] == chosen].iloc[0]
        st.session_state["selected_city"] = row["여행도시"]
        st.session_state["selected_place"]  = chosen

        log_and_render(chosen, 
                       sender="user", 
                       chat_container=chat_container,
                       key=f"user_place_{chosen}")
        handle_selected_place(
            chosen,
            travel_df, 
            external_score_df,
            festival_df, 
            weather_df,
            chat_container=chat_container
        )
        st.session_state[step_key] = "companion"
        st.rerun()        
        return


    # ────────────────── 5) 동행·연령 받기 단계
    elif st.session_state[step_key] == "companion":
        with chat_container:
            # 5.1) 안내 메시지 출력
            log_and_render(
                "함께 가는 분이나 연령대를 알려주시면 더 딱 맞는 상품을 골라드릴게요!<br>"
                "1️⃣ 동행 여부 (혼자 / 친구 / 커플 / 가족 / 단체)<br>"
                "2️⃣ 연령대 (20대 / 30대 / 40대 / 50대 / 60대 이상)",
                sender="bot",
                chat_container=chat_container,
                key="ask_companion_age"
            )

            # 5.1.1) 동행 체크박스
            st.markdown(
                '<div style="font-size:14px; font-weight:600; margin:14px 0px 6px 0px;">👫 동행 선택</div>',
                unsafe_allow_html=True
            )
            c_cols = st.columns(5)
            comp_flags = {
                "혼자":   c_cols[0].checkbox("혼자"),
                "친구":   c_cols[1].checkbox("친구"),
                "커플":   c_cols[2].checkbox("커플"),
                "가족":   c_cols[3].checkbox("가족"),
                "단체":   c_cols[4].checkbox("단체"),
            }
            companions = [k for k, v in comp_flags.items() if v]

            # 5.1.2) 연령 체크박스
            st.markdown(
                '<div style="font-size:14px; font-weight:600; margin:0px 0px 6px 0px;">🎂 연령 선택</div>',
                unsafe_allow_html=True
            )
            a_cols = st.columns(5)
            age_flags = {
                "20대": a_cols[0].checkbox("20대"),
                "30대": a_cols[1].checkbox("30대"),
                "40대": a_cols[2].checkbox("40대"),
                "50대": a_cols[3].checkbox("50대"),
                "60대 이상": a_cols[4].checkbox("60대 이상"),
            }
            age_group = [k for k, v in age_flags.items() if v]

            # 5.1.3) 확인 버튼
            confirm = st.button(
                "추천 받기",
                key="btn_confirm_companion",
                disabled=not (companions or age_group),
            )

            # 5.2) 메시지 출력
            if confirm:
                # 사용자 버블 출력
                user_msg = " / ".join(companions + age_group)
                log_and_render(
                    user_msg if user_msg else "선택 안 함",
                    sender="user",
                    chat_container=chat_container,
                    key=f"user_comp_age_{random.randint(1,999999)}"
                )

                # 세션 저장
                st.session_state["companions"] = companions or None
                st.session_state["age_group"]  = age_group  or None

                # 다음 스텝
                st.session_state[step_key] = "package"
                st.rerun()
                return
               
    
    # ────────────────── 6) 동행·연령 필터링· 패키지 출력 단계
    elif st.session_state[step_key] == "package":

        # 패키지 버블을 이미 만들었으면 건너뜀
        if st.session_state.get("package_rendered", False):
            st.session_state[step_key] = "package_end"
            return
        
        companions = st.session_state.get("companions")
        age_group = st.session_state.get("age_group")
        city = st.session_state.get("selected_city")
        place = st.session_state.get("selected_place")

        filtered = filter_packages_by_companion_age(
            package_df, companions, age_group, city=city, top_n=2
        )

        if filtered.empty:
            log_and_render(
                "⚠️ 아쉽지만 지금 조건에 맞는 패키지가 없어요.<br>"
                "다른 조건으로 다시 찾아볼까요?",
                sender="bot", chat_container=chat_container,
                key="no_package"
            )
            st.session_state[step_key] = "companion"   # 다시 입력 단계로
            st.rerun()
            return

        combo_msg = make_companion_age_message(companions, age_group)
        header = f"{combo_msg}"

        # 패키지 카드 출력
        used_phrases = set()
        theme_row = travel_df[travel_df["여행지"] == place]
        raw_theme = theme_row["통합테마명"].iloc[0] if not theme_row.empty else None
        selected_ui_theme = theme_ui_map.get(raw_theme, (raw_theme,))[0]

        title_candidates = theme_title_phrases.get(selected_ui_theme, ["추천"])
        sampled_titles = random.sample(title_candidates,
                                    k=min(2, len(title_candidates)))
        
        # 메시지 생성
        pkg_msgs = [header]

        for i, (_, row) in enumerate(filtered.iterrows(), 1):
            desc, used_phrases = make_top2_description_custom(
                row.to_dict(), used_phrases
            )
            tags = format_summary_tags_custom(row["요약정보"])
            title_phrase = (sampled_titles[i-1] if i <= len(sampled_titles)
                            else random.choice(title_candidates))
            title = f"{city} {title_phrase} 패키지"
            url = row.URL

            pkg_msgs.append(
                    f"{i}. <strong>{title}</strong><br>"
                    f"🅼 {desc}<br>{tags}<br>"
                    f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
                    'style="text-decoration:none;font-weight:600;color:#009c75;">'
                    '💚 바로가기&nbsp;↗</a>'
                )
        # 메시지 출력
        log_and_render(
                "<br><br>".join(pkg_msgs),
                sender="bot",
                chat_container=chat_container,
                key=f"pkg_bundle_{random.randint(1,999999)}"
            )
        
        # 세션 정리
        st.session_state["package_rendered"] = True
        st.session_state[step_key] = "package_end"
        return  
    
    # ────────────────── 7) 종료 단계
    elif st.session_state[step_key] == "package_end":
        log_and_render("필요하실 때 언제든지 또 찾아주세요! ✈️",
                    sender="bot", chat_container=chat_container,
                    key="goodbye")
      
# ───────────────────────────────────── intent 모드
def intent_ui(travel_df, external_score_df, festival_df, weather_df, package_df,
              country_filter, city_filter, chat_container, intent, log_and_render):
    """intent(의도를 입력했을 경우) 모드 전용 UI & 로직"""
    # ────────────────── 세션 키 정의
    sample_key = "intent_sample_df"
    step_key = "intent_step"
    prev_key = "intent_prev_places"
    intent_key = "intent_chip_selected"

    # ────────────────── 0) 초기화
    if step_key not in st.session_state:
        st.session_state[step_key] = "recommend_places"
        st.session_state[prev_key] = set()
        st.session_state.pop(sample_key, None)

    # ────────────────── 1) restart 상태면 인트로만 출력하고 종료
    if st.session_state[step_key] == "restart":
        log_and_render(
            "다시 여행지를 추천해드릴게요!<br>요즘 떠오르는 여행이 있으신가요?",
            sender="bot",
            chat_container=chat_container,
            key="region_restart_intro"
        )
        return
    
    # ────────────────── 2) 여행지 추천 단계
    if st.session_state[step_key] == "recommend_places":
        selected_theme = intent
        theme_df = recommend_places_by_theme(selected_theme, country_filter, city_filter)
        theme_df = theme_df.drop_duplicates(subset=["여행도시"])
        theme_df = theme_df.drop_duplicates(subset=["여행지"])

        # 2.1) 이전 추천 기록 세팅
        prev = st.session_state.setdefault(prev_key, set())

        # 2.2) 이미 샘플이 있다면 result_df 재사용
        if sample_key in st.session_state and not st.session_state[sample_key].empty:
            result_df = st.session_state[sample_key]
        else:
            # 2.3) 새로운 추천 대상 필터링
            candidates = theme_df[~theme_df["여행지"].isin(prev)]

            # 2.4) 후보가 없다면 종료
            if candidates.empty:
                st.session_state[step_key] = "recommend_places_end"
                st.rerun()
                return

            # 2.5) 새로운 추천 추출 및 저장
            result_df = apply_weighted_score_filter(candidates)
            st.session_state[sample_key] = result_df

            # prev에 등록하여 중복 추천 방지
            prev.update(result_df["여행지"])
            st.session_state[prev_key] = prev

        # 2.6) 오프닝 문장 생성
        opening_line = intent_opening_lines.get(selected_theme, f"'{selected_theme}' 여행지를 소개할게요.")
        opening_line = opening_line.format(len(result_df))

        # 2.7) 추천 메시지 구성
        message = "<br>".join([
            f"{i+1}. <strong>{row.여행지}</strong> "
            f"({row.여행나라}, {row.여행도시}) "
            f"{getattr(row, '한줄설명', '설명이 없습니다')}"
            for i, row in enumerate(result_df.itertuples())
        ])

        # 2.8) 챗봇 출력 + 칩 버튼 렌더링
        with chat_container:
            log_and_render(f"{opening_line}<br><br>{message}", 
                           sender="bot", 
                           chat_container=chat_container,
                           key=f"intent_recommendation_{random.randint(1,999999)}")

            recommend_names = result_df["여행지"].tolist()
            prev_choice = st.session_state.get(intent_key, None)
            choice = render_chip_buttons(
                recommend_names + ["다른 여행지 보기 🔄"],
                key_prefix="intent_chip",
                selected_value=prev_choice
            )
        # 2.9) 선택 없거나 중복 선택이면 대기   
        if not choice or choice == prev_choice:
            return

        # 선택 결과 처리
        if choice:
            if choice == "다른 여행지 보기 🔄":
                log_and_render("다른 여행지 보기 🔄", 
                   sender="user", 
                   chat_container=chat_container, 
                   key=f"user_place_refresh_{random.randint(1,999999)}")
                
                st.session_state.pop(sample_key, None)
                st.rerun()
                return
            
            # 정상 선택된 경우
            st.session_state[intent_key] = choice
            st.session_state[step_key] = "detail"
            st.session_state.chat_log.append(("user", choice))

            # 실제로 선택된 여행지만 prev에 기록
            match = result_df[result_df["여행지"] == choice]
            if not match.empty:
                prev.add(choice)
                st.session_state[prev_key] = prev

            # 샘플 폐기
            st.session_state.pop(sample_key, None)
            st.rerun()
            return  

    # ────────────────── 3) 추천 종료 단계
    elif st.session_state[step_key] == "recommend_places_end":
        # 3.1) 메시지 출력
        with chat_container:
            log_and_render(
                "⚠️ 더 이상 새로운 여행지가 없어요.<br>다시 질문하시겠어요?",
                sender="bot",
                chat_container=chat_container,
                key="intent_empty"
            )

            # 3.2) 재시작 여부 칩 버튼 출력
            restart_done_key = "intent_restart_done"
            chip_ph = st.empty()

            if not st.session_state.get(restart_done_key, False):
                with chip_ph:
                    choice = render_chip_buttons(
                        ["예 🔄", "아니오 ❌"], 
                        key_prefix="intent_restart")
            else:
                choice = None

            # 3.3) 아직 아무것도 선택하지 않은 경우
            if choice is None:
                return

            chip_ph.empty()
            st.session_state[restart_done_key] = True

            # 3.4) 사용자 선택값 출력
            log_and_render(choice, 
                           sender="user", 
                           chat_container=chat_container
                           )
            
            # 3.5) 사용자가 재추천을 원하는 경우
            if choice == "예 🔄":
                for k in [sample_key, prev_key, intent_key, restart_done_key]:
                    st.session_state.pop(k, None)
                chip_ph.empty() 

                # 다음 추천 단계로 초기화
                st.session_state["user_input_rendered"] = False
                st.session_state["intent_step"] = "restart"

                log_and_render(
                    "다시 여행지를 추천해드릴게요!<br>요즘 떠오르는 여행이 있으신가요?",
                    sender="bot",
                    chat_container=chat_container,
                    key="intent_restart_intro"
                )
                return

            # 3.6) 사용자가 종료를 선택한 경우
            else:
                log_and_render("여행 추천을 종료할게요. 필요하실 때 언제든지 또 찾아주세요! ✈️",
                               sender="bot", 
                               chat_container=chat_container,
                               key="intent_exit")
                st.stop()
            return
        
    # ────────────────── 4) 여행지 상세 단계
    if st.session_state[step_key] == "detail":
        chosen = st.session_state[intent_key]
        # city 이름 뽑아서 세션에 저장
        row = travel_df[travel_df["여행지"] == chosen].iloc[0]
        st.session_state["selected_city"] = row["여행도시"]
        st.session_state["selected_place"]  = chosen

        log_and_render(chosen, 
                       sender="user", 
                       chat_container=chat_container,
                       key=f"user_place_{chosen}")
        handle_selected_place(
            chosen,
            travel_df, 
            external_score_df,
            festival_df, 
            weather_df,
            chat_container=chat_container
        )
        st.session_state[step_key] = "companion"
        st.rerun()        
        return
    
    # ────────────────── 5) 동행·연령 받기 단계
    elif st.session_state[step_key] == "companion":
        with chat_container:
            # 5.1) 안내 메시지 출력
            log_and_render(
                "함께 가는 분이나 연령대를 알려주시면 더 딱 맞는 상품을 골라드릴게요!<br>"
                "1️⃣ 동행 여부 (혼자 / 친구 / 커플 / 가족 / 단체)<br>"
                "2️⃣ 연령대 (20대 / 30대 / 40대 / 50대 / 60대 이상)",
                sender="bot",
                chat_container=chat_container,
                key="ask_companion_age"
            )

            # 5.1.1) 동행 체크박스
            st.markdown(
                '<div style="font-size:14px; font-weight:600; margin:14px 0px 6px 0px;">👫 동행 선택</div>',
                unsafe_allow_html=True
            )
            c_cols = st.columns(5)
            comp_flags = {
                "혼자":   c_cols[0].checkbox("혼자"),
                "친구":   c_cols[1].checkbox("친구"),
                "커플":   c_cols[2].checkbox("커플"),
                "가족":   c_cols[3].checkbox("가족"),
                "단체":   c_cols[4].checkbox("단체"),
            }
            companions = [k for k, v in comp_flags.items() if v]

            # 5.1.2) 연령 체크박스
            st.markdown(
                '<div style="font-size:14px; font-weight:600; margin:0px 0px 6px 0px;">🎂 연령 선택</div>',
                unsafe_allow_html=True
            )
            a_cols = st.columns(5)
            age_flags = {
                "20대": a_cols[0].checkbox("20대"),
                "30대": a_cols[1].checkbox("30대"),
                "40대": a_cols[2].checkbox("40대"),
                "50대": a_cols[3].checkbox("50대"),
                "60대 이상": a_cols[4].checkbox("60대 이상"),
            }
            age_group = [k for k, v in age_flags.items() if v]

            # 5.1.3) 확인 버튼
            confirm = st.button(
                "추천 받기",
                key="btn_confirm_companion",
                disabled=not (companions or age_group),
            )

            # 5.2) 메시지 출력
            if confirm:
                # 사용자 버블 출력
                user_msg = " / ".join(companions + age_group)
                log_and_render(
                    user_msg if user_msg else "선택 안 함",
                    sender="user",
                    chat_container=chat_container,
                    key=f"user_comp_age_{random.randint(1,999999)}"
                )

                # 세션 저장
                st.session_state["companions"] = companions or None
                st.session_state["age_group"]  = age_group  or None

                # 다음 스텝
                st.session_state[step_key] = "package"
                st.rerun()
                return
                   
    # ────────────────── 6) 동행·연령 필터링· 패키지 출력 단계
    elif st.session_state[step_key] == "package":

        # 패키지 버블을 이미 만들었으면 건너뜀
        if st.session_state.get("package_rendered", False):
            st.session_state[step_key] = "package_end"
            return
        
        companions = st.session_state.get("companions")
        age_group = st.session_state.get("age_group")
        city = st.session_state.get("selected_city")
        place = st.session_state.get("selected_place")

        filtered = filter_packages_by_companion_age(
            package_df, companions, age_group, city=city, top_n=2
        )

        if filtered.empty:
            log_and_render(
                "⚠️ 아쉽지만 지금 조건에 맞는 패키지가 없어요.<br>"
                "다른 조건으로 다시 찾아볼까요?",
                sender="bot", chat_container=chat_container,
                key="no_package"
            )
            st.session_state[step_key] = "companion"   # 다시 입력 단계로
            st.rerun()
            return

        combo_msg = make_companion_age_message(companions, age_group)
        header = f"{combo_msg}"

        # 패키지 카드 출력
        used_phrases = set()
        theme_row = travel_df[travel_df["여행지"] == place]
        raw_theme = theme_row["통합테마명"].iloc[0] if not theme_row.empty else None
        selected_ui_theme = theme_ui_map.get(raw_theme, (raw_theme,))[0]

        title_candidates = theme_title_phrases.get(selected_ui_theme, ["추천"])
        sampled_titles = random.sample(title_candidates,
                                    k=min(2, len(title_candidates)))
        
        # 메시지 생성
        pkg_msgs = [header]

        for i, (_, row) in enumerate(filtered.iterrows(), 1):
            desc, used_phrases = make_top2_description_custom(
                row.to_dict(), used_phrases
            )
            tags = format_summary_tags_custom(row["요약정보"])
            title_phrase = (sampled_titles[i-1] if i <= len(sampled_titles)
                            else random.choice(title_candidates))
            title = f"{city} {title_phrase} 패키지"
            url = row.URL

            pkg_msgs.append(
                    f"{i}. <strong>{title}</strong><br>"
                    f"🅼 {desc}<br>{tags}<br>"
                    f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
                    'style="text-decoration:none;font-weight:600;color:#009c75;">'
                    '💚 바로가기&nbsp;↗</a>'
                )
        # 메시지 출력
        log_and_render(
                "<br><br>".join(pkg_msgs),
                sender="bot",
                chat_container=chat_container,
                key=f"pkg_bundle_{random.randint(1,999999)}"
            )
        
        # 세션 정리
        st.session_state["package_rendered"] = True
        st.session_state[step_key] = "package_end"
        return  
    
    # ────────────────── 7) 종료 단계
    elif st.session_state[step_key] == "package_end":
        log_and_render("필요하실 때 언제든지 또 찾아주세요! ✈️",
                    sender="bot", chat_container=chat_container,
                    key="goodbye")
        
# ───────────────────────────────────── emotion 모드
def emotion_ui(travel_df, external_score_df, festival_df, weather_df, package_df,
              country_filter, city_filter, chat_container, candidate_themes, 
              intent, emotion_groups, top_emotions, log_and_render):
    """emotion(감정을 입력했을 경우) 모드 전용 UI & 로직"""
    
    # ────────────────── 세션 키 정의
    sample_key = "emotion_sample_df"
    step_key = "emotion_step"
    theme_key = "selected_theme"
    emotion_key = "emotion_chip_selected"
    prev_key = "emotion_prev_places"

    # ────────────────── 0) 초기화
    if step_key not in st.session_state:
        st.session_state[step_key] = "theme_selection"
        st.session_state[prev_key]  = set()
        st.session_state.pop(sample_key, None)


    # ────────────────── 1) restart 상태면 인트로만 출력하고 종료
    if st.session_state[step_key] == "restart":
        log_and_render(
            "다시 여행지를 추천해드릴게요!<br>요즘 떠오르는 여행이 있으신가요?",
            sender="bot",
            chat_container=chat_container,
            key="region_restart_intro"
        )
        return

    # ────────────────── 2) 테마 추천 단계
    if st.session_state[step_key] == "theme_selection":
        # 추천 테마 1개일 경우
        if len(candidate_themes) == 1:
            selected_theme = candidate_themes[0]
            st.session_state[theme_key] = selected_theme
            log_and_render(f"추천 가능한 테마가 1개이므로 '{selected_theme}'을 선택할게요.", sender="bot", chat_container=chat_container)
            st.session_state[step_key] = "recommend_places"
            st.rerun()

        # 테마가 여러 개일 경우
        else:
            # 인트로 메시지
            intro_msg = generate_intro_message(intent=intent, emotion_groups=emotion_groups, emotion_scores=top_emotions)
            log_and_render(f"{intro_msg}<br>아래 중 마음이 끌리는 여행 스타일을 골라주세요 💫", sender="bot", chat_container=chat_container)

            # 후보 테마 준비
            dfs = [recommend_places_by_theme(t, country_filter, city_filter) for t in candidate_themes]
            dfs = [df for df in dfs if not df.empty]
            all_theme_df = pd.concat(dfs) if dfs else pd.DataFrame(columns=travel_df.columns)
            all_theme_df = all_theme_df.drop_duplicates(subset=["여행지"])
            all_theme_names = all_theme_df["통합테마명"].dropna().tolist()

            available_themes = []
            for t in candidate_themes:
                if t in all_theme_names and t not in available_themes:
                    available_themes.append(t)
            for t in all_theme_names:
                if t not in available_themes:
                    available_themes.append(t)
            available_themes = available_themes[:3]  # 최대 3개

            # 칩 UI 출력
            with chat_container:
                chip = render_chip_buttons(
                    [theme_ui_map.get(t, (t, ""))[0] for t in available_themes],
                    key_prefix="theme_chip"
                )

                # 선택이 완료되면 다음 단계로 이동
                if chip:
                    selected_theme = ui_to_theme_map.get(chip, chip)
                    st.session_state[theme_key] = selected_theme
                    st.session_state[step_key] = "recommend_places"
                    st.session_state["emotion_all_theme_df"] = all_theme_df
                    log_and_render(f"{chip}", sender="user",
                                chat_container=chat_container)
                    
                    st.rerun()

    # ────────────────── 3) 여행지 추천 단계
    if st.session_state[step_key] == "recommend_places":
        all_theme_df = st.session_state.get("emotion_all_theme_df", pd.DataFrame())
        selected_theme = st.session_state.get(theme_key, "")

        prev_key = "emotion_prev_places"
        prev = st.session_state.setdefault(prev_key, set())

        # 예외 처리: 데이터 없을 경우
        if all_theme_df.empty or not selected_theme:
            log_and_render("추천 데이터를 불러오는 데 문제가 발생했어요. <br>다시 입력해 주세요.", sender="bot", chat_container=chat_container)
            return
        
        if sample_key not in st.session_state:
            theme_df = all_theme_df[all_theme_df["통합테마명"] == selected_theme]
            theme_df = theme_df.drop_duplicates(subset=["여행도시"])
            theme_df = theme_df.drop_duplicates(subset=["여행지"])
            remaining = theme_df[~theme_df["여행지"].isin(prev)]

            if remaining.empty:
                st.session_state[step_key] = "recommend_places_end"
                st.rerun()
                return 

            result_df = apply_weighted_score_filter(remaining)
            st.session_state[sample_key] = result_df
        else:
            result_df = st.session_state[sample_key]

        # 추천 수 부족할 경우 Fallback 보완
        if len(result_df) < 3:
            fallback = travel_df[
                (travel_df["통합테마명"] == selected_theme) &
                (~travel_df["여행지"].isin(result_df["여행지"]))
            ].drop_duplicates(subset=["여행지"])

            if not fallback.empty:
                fill_count = min(3 - len(result_df), len(fallback))
                fill = fallback.sample(n=fill_count, random_state=random.randint(1, 9999))
                result_df = pd.concat([result_df, fill], ignore_index=True)

        # 샘플 저장
        st.session_state[sample_key] = result_df

        # 2.1)첫 문장 출력
        ui_name = theme_ui_map.get(selected_theme, (selected_theme,))[0]
        opening_line_template = theme_opening_lines.get(ui_name)
        opening_line = opening_line_template.format(len(result_df)) if opening_line_template else ""

        message = (
            "<br>".join([
                f"{i+1}. <strong>{row.여행지}</strong> "
                f"({row.여행나라}, {row.여행도시}) "
                f"{getattr(row, '한줄설명', '설명이 없습니다')}"
                for i, row in enumerate(result_df.itertuples())
            ])
        )
        if opening_line_template:
            message_combined = f"{opening_line}<br><br>{message}"
            with chat_container:
                log_and_render(message_combined, 
                                sender="bot",
                                chat_container=chat_container, 
                                key=f"emotion_recommendation_{random.randint(1,999999)}"
                                )
                # 2.2) 칩 버튼으로 추천지 중 선택받기
                recommend_names = result_df["여행지"].tolist() 
                prev_choice = st.session_state.get(emotion_key, None)
                choice = render_chip_buttons(
                    recommend_names + ["다른 여행지 보기 🔄"],
                    key_prefix="emotion_chip",
                    selected_value=prev_choice
                )
                
                # 2.3) 선택 결과 처리
                if not choice or choice == prev_choice:
                    return

                if choice == "다른 여행지 보기 🔄":
                    log_and_render("다른 여행지 보기 🔄", 
                        sender="user", 
                        chat_container=chat_container, 
                        key=f"user_place_refresh_{random.randint(1,999999)}")
                                
                    st.session_state.pop(sample_key, None)
                    st.rerun()
                    return

                # 실제 선택한 여행지 처리
                st.session_state[emotion_key] = choice
                st.session_state[step_key] = "detail"
                st.session_state.chat_log.append(("user", choice))
                
                # 선택한 여행지를 prev 기록에 추가
                match = result_df[result_df["여행지"] == choice]
                if not match.empty:
                    prev.add(choice)
                    st.session_state[prev_key] = prev

                # 샘플 폐기
                st.session_state.pop(sample_key, None)
                st.rerun()
                return
                    
    # ────────────────── 3) 추천 종료 단계: 더 이상 추천할 여행지가 없을 때
    elif st.session_state[step_key] == "recommend_place_end":
        with chat_container:
            # 3.1) 메시지 출력
            log_and_render(
                "⚠️ 더 이상 새로운 여행지가 없어요.<br>다시 질문하시겠어요?",
                sender="bot",
                chat_container=chat_container,
                key="emotion_empty"
            )
            # 3.2) 재시작 여부 칩 버튼 출력
            restart_done_key = "emotion_restart_done"
            chip_ph = st.empty() 

            if not st.session_state.get(restart_done_key, False):
                with chip_ph:
                    choice = render_chip_buttons( 
                        ["예 🔄", "아니오 ❌"],
                        key_prefix="emotion_restart"
                    )
            else:
                choice = None

            # 3.3) 아직 아무것도 선택하지 않은 경우
            if choice is None:
                return
            
            chip_ph.empty()  
            st.session_state[restart_done_key] = True

            # 3.4) 사용자 선택값 출력
            log_and_render(
                choice,
                sender="user",
                chat_container=chat_container,
                key=f"user_restart_choice_{choice}"
            )
                    
            # 3.5) 사용자가 재추천을 원하는 경우   
            if choice == "예 🔄":
                # 여행 추천 상태 초기화
                for k in [emotion_key, prev_key, sample_key, restart_done_key]:
                    st.session_state.pop(k, None)
                chip_ph.empty()  

                # 다음 추천 단계로 초기화
                st.session_state["user_input_rendered"] = False
                st.session_state["emotion_step"] = "restart"

                log_and_render(
                    "다시 여행지를 추천해드릴게요!<br>요즘 떠오르는 여행이 있으신가요?",
                    sender="bot",
                    chat_container=chat_container,
                    key="emotion_restart_intro"
                )
                return
            
            # 3.6) 사용자가 종료를 선택한 경우
            else:
                log_and_render("여행 추천을 종료할게요. 필요하실 때 언제든지 또 찾아주세요! ✈️", 
                               sender="bot", 
                               chat_container=chat_container,
                               key="emotion_exit")
                st.stop()
            return
        
    # ────────────────── 4) 여행지 상세 단계
    if st.session_state[step_key] == "detail":
        chosen = st.session_state[emotion_key]
        # city 이름 뽑아서 세션에 저장
        row = travel_df[travel_df["여행지"] == chosen].iloc[0]
        st.session_state["selected_city"] = row["여행도시"]
        st.session_state["selected_place"]  = chosen

        log_and_render(chosen, 
                       sender="user", 
                       chat_container=chat_container,
                       key=f"user_place_{chosen}")
        handle_selected_place(
            chosen,
            travel_df, 
            external_score_df,
            festival_df, 
            weather_df,
            chat_container=chat_container
        )
        st.session_state[step_key] = "companion"
        st.rerun()        
        return   
      
    # ────────────────── 5) 동행·연령 받기 단계
    elif st.session_state[step_key] == "companion":
        with chat_container:
            # 5.1) 안내 메시지 출력
            log_and_render(
                "함께 가는 분이나 연령대를 알려주시면 더 딱 맞는 상품을 골라드릴게요!<br>"
                "1️⃣ 동행 여부 (혼자 / 친구 / 커플 / 가족 / 단체)<br>"
                "2️⃣ 연령대 (20대 / 30대 / 40대 / 50대 / 60대 이상)",
                sender="bot",
                chat_container=chat_container,
                key="ask_companion_age"
            )

            # 5.1.1) 동행 체크박스
            st.markdown(
                '<div style="font-size:14px; font-weight:600; margin:14px 0px 6px 0px;">👫 동행 선택</div>',
                unsafe_allow_html=True
            )
            c_cols = st.columns(5)
            comp_flags = {
                "혼자":   c_cols[0].checkbox("혼자"),
                "친구":   c_cols[1].checkbox("친구"),
                "커플":   c_cols[2].checkbox("커플"),
                "가족":   c_cols[3].checkbox("가족"),
                "단체":   c_cols[4].checkbox("단체"),
            }
            companions = [k for k, v in comp_flags.items() if v]

            # 5.1.2) 연령 체크박스
            st.markdown(
                '<div style="font-size:14px; font-weight:600; margin:0px 0px 6px 0px;">🎂 연령 선택</div>',
                unsafe_allow_html=True
            )
            a_cols = st.columns(5)
            age_flags = {
                "20대": a_cols[0].checkbox("20대"),
                "30대": a_cols[1].checkbox("30대"),
                "40대": a_cols[2].checkbox("40대"),
                "50대": a_cols[3].checkbox("50대"),
                "60대 이상": a_cols[4].checkbox("60대 이상"),
            }
            age_group = [k for k, v in age_flags.items() if v]

            # 5.1.3) 확인 버튼
            confirm = st.button(
                "추천 받기",
                key="btn_confirm_companion",
                disabled=not (companions or age_group),
            )

            # 5.2) 메시지 출력
            if confirm:
                # 사용자 버블 출력
                user_msg = " / ".join(companions + age_group)
                log_and_render(
                    user_msg if user_msg else "선택 안 함",
                    sender="user",
                    chat_container=chat_container,
                    key=f"user_comp_age_{random.randint(1,999999)}"
                )

                # 세션 저장
                st.session_state["companions"] = companions or None
                st.session_state["age_group"]  = age_group  or None

                # 다음 스텝
                st.session_state[step_key] = "package"
                st.rerun()
                return
            
    # ────────────────── 6) 동행·연령 필터링· 패키지 출력 단계
    elif st.session_state[step_key] == "package":

        # 패키지 버블을 이미 만들었으면 건너뜀
        if st.session_state.get("package_rendered", False):
            st.session_state[step_key] = "package_end"
            return
        
        companions = st.session_state.get("companions")
        age_group = st.session_state.get("age_group")
        city = st.session_state.get("selected_city")
        place = st.session_state.get("selected_place")

        filtered = filter_packages_by_companion_age(
            package_df, companions, age_group, city=city, top_n=2
        )

        if filtered.empty:
            log_and_render(
                "⚠️ 아쉽지만 지금 조건에 맞는 패키지가 없어요.<br>"
                "다른 조건으로 다시 찾아볼까요?",
                sender="bot", chat_container=chat_container,
                key="no_package"
            )
            st.session_state[step_key] = "companion"
            st.rerun()
            return

        combo_msg = make_companion_age_message(companions, age_group)
        header = f"{combo_msg}"

        # 패키지 카드 출력
        used_phrases = set()
        theme_row = travel_df[travel_df["여행지"] == place]
        raw_theme = theme_row["통합테마명"].iloc[0] if not theme_row.empty else None
        selected_ui_theme = theme_ui_map.get(raw_theme, (raw_theme,))[0]

        title_candidates = theme_title_phrases.get(selected_ui_theme, ["추천"])
        sampled_titles = random.sample(title_candidates,
                                    k=min(2, len(title_candidates)))
        
        # 메시지 생성
        pkg_msgs = [header]

        for i, (_, row) in enumerate(filtered.iterrows(), 1):
            desc, used_phrases = make_top2_description_custom(
                row.to_dict(), used_phrases
            )
            tags = format_summary_tags_custom(row["요약정보"])
            title_phrase = (sampled_titles[i-1] if i <= len(sampled_titles)
                            else random.choice(title_candidates))
            title = f"{city} {title_phrase} 패키지"
            url = row.URL

            pkg_msgs.append(
                    f"{i}. <strong>{title}</strong><br>"
                    f"🅼 {desc}<br>{tags}<br>"
                    f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
                    'style="text-decoration:none;font-weight:600;color:#009c75;">'
                    '💚 바로가기&nbsp;↗</a>'
                )
        # 메시지 출력
        log_and_render(
                "<br><br>".join(pkg_msgs),
                sender="bot",
                chat_container=chat_container,
                key=f"pkg_bundle_{random.randint(1,999999)}"
            )
        
        # 세션 정리
        st.session_state["package_rendered"] = True
        st.session_state[step_key] = "package_end"
        return  
    
    # ────────────────── 7) 종료 단계
    elif st.session_state[step_key] == "package_end":
        log_and_render("필요하실 때 언제든지 또 찾아주세요! ✈️",
                    sender="bot", chat_container=chat_container,
                    key="goodbye")    
        
# ───────────────────────────────────── unknown 모드
def unknown_ui(country, city, chat_container, log_and_render):
    """unknown 모드(아직 DB에 없는 나라·도시일 때 안내) 전용 UI & 로직"""
    # 안내 메시지
    if city:
        msg = (f"🔍 죄송해요. 해당 <strong>{city}</strong>의 여행지는 "
               "아직 준비 중이에요.<br> 빠른 시일 안에 업데이트할게요!")
    elif country:
        msg = (f"🔍 죄송해요. 해당 <strong>{country}</strong>의 여행지는 "
               "아직 준비 중이에요.<br> 빠른 시일 안에 업데이트할게요!")
    else:
        msg = "🔍 죄송해요. 해당 여행지는 아직 준비 중이에요."

    with chat_container:
        log_and_render(
            f"{msg}",
            sender="bot",
            chat_container=chat_container,
            key="unknown_dest"
        )

# ───────────────────────────────────── 챗봇 호출
def main(): 

    init_session()
    chat_container = st.container()

    if "chat_log" in st.session_state and st.session_state.chat_log:
        replay_log(chat_container)

    # ───── greeting 메시지 출력
    if not st.session_state.get("greeting_rendered", False):
            greeting_message = (
                "안녕하세요. <strong>모아(MoAi)</strong>입니다.🤖<br><br>"
                "요즘 어떤 여행이 떠오르세요?<br>""모아가 딱 맞는 여행지를 찾아드릴게요."
            )
            log_and_render(
                greeting_message,
                sender="bot",
                chat_container=chat_container,
                key="greeting"
            )
            st.session_state["greeting_rendered"] = True


    # ───── 사용자 입력 & 추천 시작 
    # 1) 사용자 입력
    user_input = st.text_input(
        "입력창", # 비어있지 않은 라벨(접근성 확보)
        placeholder="ex)'요즘 힐링이 필요해요', '가족 여행 어디가 좋을까요?'",
        key="user_input",
        label_visibility="collapsed",  # 화면에선 숨김
    )
    user_input_key = "last_user_input"
    select_keys = ["intent_chip_selected", "region_chip_selected", "emotion_chip_selected", "theme_chip_selected"]
        
    # 1-1) “진짜 새로 입력” 감지
    prev = st.session_state.get(user_input_key, "")
    if user_input and user_input != prev:
        for k in select_keys:
            st.session_state.pop(k, None)
        st.session_state[user_input_key] = user_input
        st.session_state["user_input_rendered"] = False

        # step 초기화
        st.session_state["region_step"] = "recommend"
        st.rerun()

    # 1-2) 사용자 메시지 한 번만 렌더링
    if user_input and not st.session_state.get("user_input_rendered", False):
        log_and_render(
            user_input,
            sender="user",
            chat_container = chat_container,
            key=f"user_input_{user_input}"
            
        )
        st.session_state["user_input_rendered"] = True

    if user_input:
        # 2) mode 탐지
        _, _, mode = detect_location_filter(user_input)
        top_emotions, emotion_groups = analyze_emotion(user_input)
        intent, intent_score = detect_intent(user_input)
        country_filter, city_filter, _ = detect_location_filter(user_input)
        candidate_themes = extract_themes(
            emotion_groups,
            intent,
            force_mode=(intent_score >= 0.70)
        )
        if intent_score >= 0.70:
            mode = "intent"

        # 🌟 DEBUG ────────────────────────────────
        # with st.expander("🔍 DEBUG - 모드 판정", expanded=True):
        #     st.markdown(f"""
        #     **입력 문장**: `{user_input}`  
        #     **detect_location_filter** 👉  
        #     • country&nbsp;→ `{country_filter}`  
        #     • city&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;→ `{city_filter}`  
        #     • mode&nbsp;&nbsp;→ `{mode}`  

        #     **intent_score**: `{intent_score:.3f}`  
        #     **top_emotions**: `{top_emotions}`  
        #     """)
        # ────────────────────────────────────────

        # 3) 모드별 분기
        if mode == "region":
            region_ui(
                travel_df,
                external_score_df,
                festival_df,
                weather_df,
                package_df,
                country_filter,
                city_filter,
                chat_container,
                log_and_render
            )
            return

        elif mode == "intent":
            intent_ui(
                travel_df, 
                external_score_df, 
                festival_df, 
                weather_df, 
                package_df,
                country_filter, 
                city_filter, 
                chat_container, 
                intent, 
                log_and_render)
            return
        
        elif mode == "unknown": 
            unknown_ui(
                country_filter, 
                city_filter, 
                chat_container, 
                log_and_render)
            return
        
        else:
            emotion_ui(
                travel_df,
                external_score_df,
                festival_df,
                weather_df,
                package_df,
                country_filter,
                city_filter,
                chat_container,
                candidate_themes,
                intent,   
                emotion_groups,   
                top_emotions,      
                log_and_render
            )

if __name__ == "__main__":
    main()


#cmd 입력-> cd "파일 위치 경로 복붙"
#ex(C:\Users\gayoung\Desktop\multi\0514 - project\06 - streamlit 테스트\test)
#cmd 입력 -> streamlit run app.py
