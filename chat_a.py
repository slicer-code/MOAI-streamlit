#!/usr/bin/env python
# coding: utf-8

# In[10]:


import pandas as pd
import torch
from sentence_transformers import SentenceTransformer, util
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch.nn.functional as F
from collections import defaultdict
from datetime import datetime
import random
import re
from css import log_and_render
import streamlit as st, pandas as pd, json, requests
# -------------------- 모델 및 데이터 로딩 --------------------
# 모델 로딩 부분을 함수로 만들고 데코레이터 추가
@st.cache_resource
def load_sbert_model():
    print("SBERT 모델 로딩 중... (이 메시지는 한 번만 보여야 합니다)")
    # 'jhgan/ko-sroberta-multitask' 대신 더 가벼운 다국어 모델로 변경
    return SentenceTransformer("distiluse-base-multilingual-cased-v1")

@st.cache_resource
def load_sentiment_model():
    print("감성 분석 모델 로딩 중... (이 메시지는 한 번만 보여야 합니다)")
    # 'hun3359/klue-bert-base-sentiment' 대신 더 가벼운 모델로 변경
    model = AutoModelForSequenceClassification.from_pretrained("monologg/distilkobert")
    model.eval()
    return model

@st.cache_resource
def load_tokenizer():
    print("토크나이저 로딩 중... (이 메시지는 한 번만 보여야 합니다)")
    # 'hun3359/klue-bert-base-sentiment' 대신 더 가벼운 모델로 변경
    return AutoTokenizer.from_pretrained("monologg/distilkobert")


@st.cache_data(show_spinner=False)
def load_csv_any(p):
    return pd.read_csv(p) if str(p).startswith(("http://","https://")) else pd.read_csv(p)

trip_url = st.secrets.get("TRIPDATA_URL")
if not trip_url:
    st.error("TRIPDATA_URL 미설정: Streamlit Secrets에 URL을 넣어주세요.")
    st.stop()

travel_df = load_csv_any(trip_url)
festival_df = pd.read_csv("전처리_통합지역축제.csv")
external_score_df = pd.read_csv("클러스터_포함_외부요인_종합점수_결과_최종.csv")
external_score_df.columns = external_score_df.columns.str.strip()
weather_df = pd.read_csv("전처리_날씨_통합_07_08.csv")
package_df = pd.read_csv("모두투어_컬럼별_개수_07_08.csv")
package_df.columns = package_df.columns.str.strip()
master_df = pd.read_csv("나라_도시_리스트.csv")

countries = travel_df["여행나라"].dropna().unique().tolist()
cities = travel_df["여행도시"].dropna().unique().tolist()
    
def detect_location_filter(text, intent_score=None):
    def in_text_exact(word):
        return word in text
        
    master_cities_list = master_df["여행도시"].dropna().unique()
    master_countries_list = master_df["여행나라"].dropna().unique()
    
    found_city = next((c for c in master_cities_list if c in text), None)
    found_country = next((c for c in master_countries_list if c in text), None)
    
    # 1. 이름조차 찾지 못했다면 intent_score 확인
    if not found_city and not found_country:
        if intent_score is not None and intent_score >= 0.70:
            return None, None, "intent"
        else:
            return None, None, "emotion"
        
    # 2. 명확한 도시/나라가 있을 경우 → region
    if found_city and not found_country:       
        match = master_df[master_df["여행도시"] == found_city]
        if not match.empty:
            found_country = match.iloc[0]["여행나라"]
                              
    is_city_recommendable = found_city in cities if found_city else False
    is_country_recommendable = found_country in countries if found_country else False

    if is_city_recommendable or is_country_recommendable:
        return found_country, found_city, "region"
    return found_country, found_city, "unknown"
# -------------------- 감정 키워드 설정 --------------------
klue_emotions = {
    0: "분노", 1: "툴툴대는", 2: "좌절한", 3: "짜증내는", 4: "방어적인", 5: "악의적인",
    6: "안달하는", 7: "구역질 나는", 8: "노여워하는", 9: "성가신", 10: "슬픔", 11: "실망한",
    12: "비통한", 13: "후회되는", 14: "우울한", 15: "마비된", 16: "염세적인", 17: "눈물이 나는",
    18: "낙담한", 19: "환멸을 느끼는", 20: "불안", 21: "두려운", 22: "스트레스 받는",
    23: "취약한", 24: "혼란스러운", 25: "당혹스러운", 26: "회의적인", 27: "걱정스러운",
    28: "조심스러운", 29: "초조한", 30: "상처", 31: "질투하는", 32: "배신당한", 33: "고립된",
    34: "충격 받은", 35: "가난한 불우한", 36: "희생된", 37: "억울한", 38: "괴로워하는",
    39: "버려진", 40: "당황", 41: "고립된(당황한)", 42: "남의 시선을 의식하는", 43: "외로운",
    44: "열등감", 45: "죄책감의", 46: "부끄러운", 47: "혐오스러운", 48: "한심한",
    49: "혼란스러운(당황한)", 50: "기쁨", 51: "감사하는", 52: "신뢰하는", 53: "편안한",
    54: "만족스러운", 55: "흥분", 56: "느긋", 57: "안도", 58: "신이 난", 59: "자신하는"
}

kote_emotion_groups = {
    "신남": [
        "기쁨", "흥분", "신이 난", "자신하는", "만족스러운"  
    ],
    "감탄": [
        "감사하는", "놀라운", "감동적인", "경외감", "신기한", "감탄" 
    ],
    "편안함": [
        "편안한", "안도", "느긋", "신뢰하는", "조용한"  
    ],
    "안정": [
        "불안", "두려운", "걱정스러운", "초조한", "취약한", "긴장된"  
    ],
    "위로": [
        "외로운", "고립된", "버려진", "상처", "낙담한", "실망한", "슬픔", "우울한", "눈물이 나는"
    ],
    "감정전환": [
        "분노", "노여워하는", "악의적인", "툴툴대는", "염세적인", "한심한", "답답한", "짜증내는","스트레스 받는"
    ],
    "혼란회복": [
        "혼란스러운", "당혹스러운", "고립된(당황한)", "혼란스러운(당황한)",
        "남의 시선을 의식하는", "부끄러운", "마비된", "죄책감의"
    ],
    "해방": [
        "성가신", "스트레스 받는", "답답한", "억울한", "탈출하고 싶은"
    ],
    "기대감": [
        "설레는", "기대되는", "두근거리는", "간절한", "희망적인"
    ],
    "부정": [
        "구역질 나는", "질투하는", "배신당한", "충격 받은", "혐오스러운", "가난한 불우한",
        "희생된", "좌절한", "방어적인", "회의적인", "열등감"
    ]
}

klue_label_to_group = {}
klue_to_general = {}

# label → group 매핑 준비
for group, keywords in kote_emotion_groups.items():
    for word in keywords:
        klue_label_to_group[word] = group

# klue_emotions에 있는 감정 키들을 그룹화
for klue_id, klue_label in klue_emotions.items():
    group = klue_label_to_group.get(klue_label, "부정")
    klue_to_general[klue_id] = group

emotion_override_dict = {
    # 위로
    "기분이 안 좋아": ("우울한", "위로"),
    "기운이 없어": ("낙담한", "위로"),
    "힘들어": ("슬픔", "위로"),
    "지쳤어": ("슬픔", "위로"),
    "피곤해": ("우울한", "위로"),
    "외로워": ("외로운", "위로"),
    "울적해": ("우울한", "위로"),
    "허전해": ("슬픔", "위로"),
    "무기력해": ("우울한", "위로"),
    "마음이 허해": ("낙담한", "위로"),
    "눈물이 나": ("눈물이 나는", "위로"),
    "속상해": ("실망한", "위로"),
    "의욕이 없어": ("우울한", "위로"),
    "지치고 힘들어": ("슬픔", "위로"),
    "마음이 아파": ("슬픔", "위로"),

    # 감정전환
    "답답해": ("짜증내는", "감정전환"),
    "짜증나": ("짜증내는", "감정전환"),
    "화나": ("분노", "감정전환"),
    "스트레스 받아": ("스트레스 받는", "감정전환"),
    "스트레스": ("스트레스 받는", "감정전환"),
    "짜증": ("짜증내는", "감정전환"),
    "터질 것 같아": ("분노", "감정전환"),
    "폭발할 것 같아": ("노여워하는", "감정전환"),
    "열받아": ("분노", "감정전환"),
    "화가 치밀어": ("노여워하는", "감정전환"),
    "머리 아파": ("성가신", "감정전환"),
    

    # 편안함
    "조용한 곳": ("편안한", "편안함"),
    "조용한": ("편안한", "편안함"),
    "한적한 데 가고 싶어": ("편안한", "편안함"),
    "쉴 곳": ("안도", "편안함"),
    "마음이 편한 곳": ("편안한", "편안함"),
    "편안한 여행": ("편안한", "편안함"),
    "힐링이 필요해": ("편안한", "편안함"),
    "아무 생각 없이 쉬고 싶어": ("느긋", "편안함"),

    # 감탄
    "감동받고 싶어": ("감사하는", "감탄"),
    "감동적인": ("감사하는", "감탄"),
    "감동": ("감사하는", "감탄"),
    "놀라운 경험": ("감탄", "감탄"),
    "신기한 거": ("감탄", "감탄"),
    "인상적인": ("감탄", "감탄"),
    "경이로운": ("감탄", "감탄"),
    "감탄할 만한": ("감탄", "감탄"),
    "와 하고 싶어": ("감탄", "감탄"),

    # 신남
    "설레": ("신이 난", "신남"),
    "신나": ("신이 난", "신남"),
    "행복해": ("기쁨", "신남"),
    "기대돼": ("기쁨", "신남"),
    "재밌는 거": ("기쁨", "신남"),
    "기분 좋음": ("기쁨", "신남"),
    "즐거운 여행": ("기쁨", "신남"),
    "들뜬다": ("흥분", "신남"),

    # 혼란회복
    "혼란스러워": ("혼란스러운", "혼란회복"),
    "헷갈려": ("혼란스러운", "혼란회복"),
    "마음이 복잡해": ("혼란스러운", "혼란회복"),
    "정리가 안 돼": ("혼란스러운", "혼란회복"),
    "머리가 복잡해": ("혼란스러운", "혼란회복"),
    "정신없어": ("혼란스러운", "혼란회복"),

    # 안정
    "안정이 필요해": ("불안", "안정"),
    "불안해": ("불안", "안정"),
    "긴장돼": ("초조한", "안정"),
    "마음이 불편해": ("걱정스러운", "안정"),
    "좀 진정하고 싶어": ("안도", "안정"),
    "안정": ("안도", "안정"),

    # 부정
    "살기 싫어": ("염세적인", "부정"),
    "인생이 재미없어": ("염세적인", "부정"),
    "세상이 싫다": ("환멸을 느끼는", "부정"),
    "세상이 싫어": ("환멸을 느끼는", "부정"),
    "다 귀찮아": ("마비된", "부정"),
    "그냥 사라지고 싶어": ("버려진", "부정"),
    "의미가 없어": ("환멸을 느끼는", "부정")
}

# -------------------- 의도기반 키워드 --------------------
intent_keywords = {
    "쇼핑" : ["쇼핑", "기념품", "득템", "특산품", "사고 싶어", "쇼핑몰", "현지 물품"],
    "실내" : ["실내", "비 오는 날 갈만한 데", "실내 장소", "실내 관광", "실내 데이트 코스"],
    "가족" : ["가족", "가족끼리", "가족과 함께", "아이와 갈만한 데", "가족여행", "부모님이랑 여행", "가족 단위", "아이 동반"],
    "워터파크" : ["워터파크", "물놀이", "워터 슬라이드 타러", "수영장", "파도풀", "어트랙션"],
    "자연" : ["자연", "풍경 좋은", "공기 좋은"],
    "전망" : ["전망", "뷰 좋은", "탁 트인", "경치 좋은", "전망대"],
    "포토존" : ["포토존", "사진 찍다", "인생샷", "인스타용", "사진 명소", "포토 스팟", "이쁘게 찍히는 곳"],
    "해양체험" : ["해양 체험", "스노클링", "다이빙", "수상 체험", "해양 액티비티", "해양 스포츠"],
    "수족관" : ["수족관", "아쿠아리움", "물고기 보러", "해양 생물 보러"],
    "종교" : ["종교", "웅장한 건축물", "성스러운 분위기", "명상", "종교적", "기도"],
    "성당" : ["성당", "성지순례", "역사 깊은 성당", "대성당", "가우디"],
    "예식장" : ["결혼식", "웨딩 촬영", "웨딩", "예식장"],
    "커플" : ["커플", "연인", "데이트 코스", "여자친구", "남자친구"],
    "랜드마크" : ["랜드마크", "유명한 장소", "대표 명소", "도시 명소", "시그니처 스팟", "상징적인", "꼭 들러야 하는"],
    "역사" : ["역사적인", "웅장한 건축물", "옛날 건축물", "역사", "전통 깊은", "유적지"],
    "궁전" : ["궁전", "웅장한 건축물", "왕이 살던", "고궁"],
    "문화체험" : ["전통 체험", "문화 체험", "문화적 경험"],
    "박물관" : ["박물관"],
    "예술감상" : ["예술 작품", "예술 작품 감상", "창의력 자극"],
    "체험관" : ["과학관", "실내 체험"],
    "광장" : ["도시 중심지", "사람 많은", "광장"],
    "산책" : ["산책", "걷기 편한", "산책로"],
    "미술관" : ["미술관", "그림 보러", "전시회 데이트", "아트 갤러리"],
    "공연" : ["오페라", "극장", "연극", "공연"],
    "유람선" :["유람선", "바다 위", "크루즈", "수상 관광", "배 타고"],
    "야경" : ["야경", "밤에 가기 좋은", "불빛 예쁜", "야경 명소", "야경 감상", "야경 스팟"],
    "이동관광" : ["차량 투어", "시티 투어", "이동하면서", "투어"],
    "공원" : ["공원"],
    "도심공원" : ["도심공원", "도시와 공원을 함께"],
    "문화거리" : ["전통 있는 거리", "예술 거리", "감성 골목", "문화 거리", "골목길", "분위기 있는 거리"],
    "호수" : ["호수", "호수 뷰 좋은", "물가 근처 조용한 데"],
    "휴양지" : ["휴식", "휴양지", "쉬는 곳", "조용한 휴양지"],
    "성" : ["성"],
    "관람차" : ["관람차", "하늘에서"],
    "테마전시" : ["특정 주제 전시", "체험형 전시", "이색 전시"],
    "강" : ["강", "강변 뷰"],
    "경기장" : ["축구장", "경기장", "응원"],
    "사원" : ["사찰", "사원", "불상"],
    "시장" : ["시장", "길거리 음식"],
    "야시장" : ["야시장", "밤에 여는 시장", "밤에 먹거리 많은 데", "포장마차 거리", "밤 분위기 좋은 시장"],
    "동물원" : ["동물원", "동물"],    
    "기차" : ["기차", "열차", "관광열차"],
    "항구" : ["항구 도시", "항구", "항구 풍경", "항구 마을"],
    "겨울스포츠" : ["스키", "스노보드", "겨울 액티비티", "겨울 스포츠", "설경 보면서 스포츠"],
    "식물원" : ["식물원", "식물 구경"],
    "케이블카" : ["케이블카"],
    "해변" : ["바다", "해변", "모래사장", "모래", "파도", "해수욕장"],
    "테마파크" : ["놀이공원", "테마파크", "놀이터", "어트랙션", "놀이기구"],
    "트레킹" : ["트레킹", "산 따라 걷기", "자연 속 걷기"],
    "섬" : ["조용한 섬 마을", "섬"],
    "미식" : ["미식", "맛있는", "현지 음식", "먹거리 투어", "맛집"],
    "버스" : ["버스"],
    "기념관" : ["기념관"],
    "신사" : ["신사", "토리이"]    
}
intent_to_category = {k: [k] for k in intent_keywords.keys()}
category_mapping = {k: k for k in intent_keywords.keys()}

emotion_to_category_boost = {
    "신남": ["테마파크", "해양체험", "미식", "문화거리", "야시장", "워터파크"],
    "기대감": ["랜드마크","전망", "문화체험", "이동관광", "포토존", "공연"],
    "편안함": ["자연", "산책", "공원", "해변", "호수", "식물원", "도심공원"],
    "안정": ["휴양지", "호수", "성당", "미술관", "예술감상"],
    "감탄": ["랜드마크", "전망", "야경", "예술감상", "역사", "종교", "포토존"],
    "혼란회복": ["종교", "도심공원", "미술관", "산책", "트레킹"],
    "감정전환": ["테마파크", "동물원", "수족관", "문화체험", "쇼핑", "미식"],
    "위로": ["자연", "호수", "동물원", "휴양지", "성당"],
    "부정": ["자연", "공원", "섬"]
}

# ---------------------안내문구 매핑 --------------------
theme_ui_map = {
    "자연/풍경 감상형": ("힐링 여행지 🧘", "자연과 풍경 속에서 편안해지는 조용한 휴식"),
    "가족/체험 투어형": ("체험 여행지 🎢", "이색적인 활동으로 즐기는 생생한 전환"),
    "쇼핑/거리 체험형": ("쇼핑 여행지 🛍", "설렘 가득한 거리에서 현지의 색을 담은 즐거움"),
    "박물관/문화 감상형": ("문화 여행지 🎨", "예술과 전통이 살아있는 공간에서 느끼는 감동"),
    "랜드마크/종교 건축형": ("명소 여행지 🏛", "감탄을 부르는 풍경과 함께 도시의 상징을 만나다"),
}
ui_to_theme_map = {v[0]: k for k, v in theme_ui_map.items()}

theme_opening_lines = {
    "힐링 여행지 🧘": "여유와 자연을 느낄 수 있는 ‘힐링 여행지’ {}곳을 추천드릴게요.",
    "체험 여행지 🎢": "몸과 마음이 들뜨는 ‘체험 여행지’ {}곳을 추천드릴게요.",
    "문화 여행지 🎨": "예술과 이야기가 있는 ‘문화 여행지’ {}곳을 추천드릴게요.",
    "쇼핑 여행지 🛍": "현지 먹거리가 가득한 ‘쇼핑 여행지’ {}곳을 추천드릴게요.",
    "명소 여행지 🏛": "문화와 상징이 깃든 ‘명소 여행지’ {}곳을 추천드릴게요.",
}

intent_opening_lines = {
    "쇼핑": "🛍 현지 물품이 가득한 쇼핑하기 좋은 여행지 추천드릴게요.",
    "실내": "🏠 비 오는 날에도 즐길 수 있는 실내 여행지를 추천드릴게요.",
    "가족": "👨‍👩‍👧‍👦 가족 모두 함께 즐길 수 있는 따뜻한 여행지를 소개할게요.",
    "워터파크": "💦 신나게 물놀이할 수 있는 워터파크 명소를 추천드릴게요.",
    "자연": "🌿 푸르른 풍경과 자연을 느낄 수 있는 여행지를 소개할게요.",
    "전망": "🔭 한눈에 뷰가 들어오는 전망 좋은 여행지를 추천드릴게요.",
    "포토존": "📸 인생샷 남기기 좋은 포토 스팟 여행지를 소개할게요.",
    "해양체험": "🤿 스노클링, 다이빙 등 해양 액티비티 명소를 추천드릴게요.",
    "수족관": "🐠 해양 생물을 가까이서 만날 수 있는 수족관을 소개할게요.",
    "종교": "🕍 성스러운 분위기를 느낄 수 있는 종교 명소를 추천드릴게요.",
    "성당": "⛪ 역사 깊은 아름다운 성당 여행지를 추천드릴게요.",
    "예식장": "💒 로맨틱한 웨딩 촬영지와 예식장을 소개할게요.",
    "커플": "💕 데이트하기 좋은 로맨틱한 커플 여행지를 추천드릴게요.",
    "랜드마크": "📍 도시를 대표하는 상징적인 명소를 소개할게요.",
    "역사": "📜 과거의 이야기가 담긴 역사적인 장소를 추천드릴게요.",
    "궁전": "🏰 화려한 궁전과 왕실의 흔적이 담긴 여행지를 소개할게요.",
    "문화체험": "🧵 전통을 직접 체험할 수 있는 문화 여행지를 추천드릴게요.",
    "박물관": "🏛 지식을 쌓을 수 있는 박물관 여행지를 추천드릴게요.",
    "예술감상": "🎨 감성과 창의력이 자극되는 예술 공간을 소개할게요.",
    "체험관": "🧪 직접 배우고 즐길 수 있는 체험형 공간을 추천드릴게요.",
    "광장": "🧭 현지 분위기를 느낄 수 있는 활기찬 광장을 소개할게요.",
    "산책": "🚶 조용히 걷기 좋은 산책 코스를 추천드릴게요.",
    "미술관": "🖼 전시회와 그림 감상이 가능한 미술관 명소를 소개할게요.",
    "공연": "🎭 공연과 무대를 즐길 수 있는 극장 여행지를 추천드릴게요.",
    "유람선": "🚢 바다 위에서 즐기는 유람선 여행지를 소개할게요.",
    "야경": "🌃 밤하늘과 불빛이 아름다운 야경 명소를 추천드릴게요.",
    "이동관광": "🚌 차량으로 편하게 이동하며 즐기는 투어 여행지를 소개할게요.",
    "공원": "🌳 자연을 품은 여유로운 공원을 추천드릴게요.",
    "도심공원": "🏞 도시 속 쉼표가 되어줄 도심공원을 소개할게요.",
    "문화거리": "🧱 예술과 전통이 깃든 감성 골목길 여행지를 추천드릴게요.",
    "호수": "🏞 잔잔한 물결이 있는 힐링 호수 명소를 소개할게요.",
    "휴양지": "🌴 조용히 쉬어가기 좋은 휴양지 곳을 추천드릴게요.",
    "성": "🏯 중세 분위기를 느낄 수 있는 고풍스러운 성을 소개할게요.",
    "관람차": "🎡 하늘 위에서 풍경을 즐길 수 있는 관람차 명소를 추천드릴게요.",
    "테마전시": "🖼 이색적인 테마 전시로 가득한 공간을 소개할게요.",
    "강": "🌊 물길 따라 여유를 느낄 수 있는 강변 여행지를 추천드릴게요.",
    "경기장": "⚽ 스포츠의 열기가 가득한 경기장 여행지를 소개할게요.",
    "사원": "🛕 고요한 분위기의 전통 사찰 여행지를 추천드릴게요.",
    "시장": "🧺 현지 분위기가 살아있는 전통 시장을 소개할게요.",
    "야시장": "🌙 밤이 더 아름다운 야시장 먹거리 여행지를 추천드릴게요.",
    "동물원": "🦁 귀여운 동물들을 만날 수 있는 동물원 명소를 추천드릴게요.",
    "기차": "🚂 느릿하게 달리는 기차와 함께하는 여행지를 소개할게요.",
    "항구": "⚓ 바다와 도시가 만나는 항구 풍경 명소를 추천드릴게요.",
    "겨울스포츠": "⛷ 스키와 보드로 겨울을 즐길 수 있는 스포츠 여행지를 소개할게요.",
    "식물원": "🌺 푸르른 식물이 가득한 식물원 힐링 공간을 추천드릴게요.",
    "케이블카": "🚡 하늘에서 풍경을 감상할 수 있는 케이블카 여행지를 소개할게요.",
    "해변": "🏖 햇살과 파도가 반기는 해변 명소를 추천드릴게요.",
    "테마파크": "🎠 어트랙션과 재미가 가득한 테마파크 여행지를 소개할게요.",
    "트레킹": "🥾 자연 속을 걷는 트레킹 여행지를 추천드릴게요.",
    "섬": "🏝 바다 위 고요한 섬 여행지를 소개할게요.",
    "미식": "🍽 현지 음식을 맛볼 수 있는 미식 여행지를 추천드릴게요.",
    "버스": "🚌 이동이 편리한 버스 투어 여행지를 소개할게요.",
    "기념관": "🗿 기억을 간직한 기념관 여행지를 추천드릴게요.",
    "신사": "⛩ 신비롭고 평온한 분위기의 신사 여행지를 소개할게요.",
}
#--------------------패키지 문구---------------------------
theme_title_phrases = {
    "힐링 여행지 🧘": [
        "완전 휴식 힐링", "조용한 쉼표 감성", "마음 회복 여정", "여유 가득 치유", "재충전 슬로우 라이프",
        "혼자만의 위로 여행", "스트레스 해소 힐링", "편안한 하루 쉼", "무리 없는 휴식 코스", "고요한 자연 속 여유"
    ],
    "체험 여행지 🎢": [
        "액티비티 가득 체험", "전통+현지활동 즐기기", "오감만족 현지 체험", "생생한 투어 중심", "로컬 라이프 몰입형",
        "이색 활동 탐험 여행", "다채로운 체험 나들이", "직접 해보는 체험 위주", "참여형 투어 여행", "이색적인 하루 체험"
    ],
    "문화 여행지 🎨": [
        "감성 깊은 문화 산책", "예술+역사 감상 투어", "전통과 현대의 조화", "미술과 공연 탐방형", "고요한 박물관 여행",
        "유산 따라 걷는 길", "명화 따라 가는 여행", "인문학 감성 문화 코스", "예술품과 함께하는 여정", "전시+예술 감상 중심"
    ],
    "쇼핑 여행지 🛍": [
        "현지 감성 쇼핑", "트렌디 마켓 탐방", "먹거리+기념품 거리투어", "핫플 마켓 나들이", "로컬 브랜드 쇼핑",
        "시장 골목 체험형 쇼핑", "감성 소품 수집 여행", "실속형 쇼핑 탐방", "득템 투어 여행", "즐거운 거리 탐방"
    ],
    "명소 여행지 🏛": [
        "랜드마크 집중 투어", "유명 명소 핵심일정", "도시 상징 명소여행", "사진 맛집 스팟 투어", "대표 장소 완전정복",
        "상징적 장소 따라가기", "유적+건축 핵심 코스", "도시 한눈에 보기 여행", "베스트 명소 몰아보기", "상징 명소 스탬프 투어"
    ]
}

feature_phrase_map = {
    frozenset(["숙소", "일정"]): [
        "편안한 숙소와 알찬 일정이 돋보이는 여행이에요", "조용한 숙소에서 시작해 일정까지 여유롭게 즐겨보세요",
        "숙소와 일정 모두 균형잡힌 완벽한 여행이 기다려요"
    ],
    frozenset(["숙소", "가이드"]): [
        "친절한 가이드와 편안한 숙소가 여행의 품격을 높여줘요", "믿음직한 가이드와 푹 쉴 수 있는 숙소가 조화를 이뤄요",
        "좋은 숙소와 세심한 가이드가 잊지 못할 추억을 만들어줘요"
    ],
    frozenset(["숙소", "식사"]): [
        "맛있는 음식과 포근한 숙소가 하루를 완벽하게 마무리해줘요", "편안한 숙소에서 휴식하고, 입맛 돋우는 식사까지 즐겨보세요",
        "숙소와 식사 모두 기대 이상! 하루가 즐거워지는 조합이에요"
    ],
    frozenset(["숙소", "가성비"]): [
        "합리적인 가격에 숙소 퀄리티까지 만족스러운 여행이에요", "가성비 좋고 편한 숙소 덕분에 여유로운 여행이 가능해요",
        "가성비와 숙소 퀄리티 모두 잡은 최고의 선택이에요"
    ],
    frozenset(["숙소", "이동수단"]): [
        "숙소와 교통 모두 걱정 없는 편안한 여행 코스예요", "편한 숙소와 편리한 이동으로 피로 없이 즐겨요",
        "숙소 위치도 좋고 이동도 편해서 스트레스 없는 일정이에요"
    ],
    frozenset(["일정", "가이드"]): [
        "계획적인 일정과 세심한 가이드가 함께하는 만족도 높은 여행이에요", "친절한 가이드의 안내로 일정이 훨씬 알차고 편안해요",
        "시간 낭비 없이 똑똑하게 즐기는 일정, 믿음직한 가이드까지 완벽해요"
    ],
    frozenset(["일정", "식사"]): [
        "시간 알차고 식사까지 만족도 높은 구성이에요", "일정이 짜임새 있고, 식사도 군더더기 없어요",
        "식사 시간이 기다려질 만큼 구성 좋은 일정이에요"
    ],
    frozenset(["일정", "가성비"]): [
        "알찬 일정과 가성비 높은 구성으로 만족스러운 여행이에요", "시간도 돈도 아끼는 실속 있는 일정이에요",
        "지루하지 않은 알찬 일정과 착한 가격, 가성비 최고에요"
    ],
    frozenset(["일정", "이동수단"]): [
        "효율적인 일정과 편리한 이동으로 스트레스 없는 여행이에요", "이동이 편해서 일정이 더 즐겁고 여유로워요",
        "부드러운 이동 루트와 알찬 일정의 조화가 인상 깊어요"
    ],
    frozenset(["가이드", "식사"]): [
        "친절한 가이드와 맛있는 음식이 감동을 더해줘요", "가이드의 설명과 맛있는 음식으로 여행이 풍성해져요",
        "입도 마음도 만족스러운 식사와 가이드 조합이에요"
    ],
    frozenset(["가이드", "가성비"]): [
        "세심한 안내와 좋은 구성, 가격까지 잡은 실속 있는 여행이에요", "저렴한 가격에도 훌륭한 가이드를 만날 수 있어요",
        "가격 대비 서비스 최고! 가이드 덕에 더 알차고 완벽해요"
    ],
    frozenset(["가이드", "이동수단"]): [
        "믿음직한 가이드와 쾌적한 이동수단으로 편안한 여행이에요", "가이드의 동선 설계가 이동을 훨씬 효율적으로 만들어줘요",
        "편안한 이동과 노련한 가이드의 조합으로 긴 여정도 든든해요"
    ],
    frozenset(["식사", "가성비"]): [
        "만족스러운 식사와 가격까지 착한 여행 코스예요", "음식 퀄리티와 가성비까지 잡은 패키지 구성이에요",
        "식사도 푸짐하고 가격도 합리적인 최고의 구성!"
    ],
    frozenset(["식사", "이동수단"]): [
        "여유로운 이동과 든든한 식사로 여행이 더욱 즐거워요", "편안한 버스 타고 가는 길마다 맛집 투어 같은 경험이에요",
        "친절한 이동기사님과 맛있는 식사가 조화로운 패키지에요"
    ],
    frozenset(["가성비", "이동수단"]): [
        "교통 편의성과 가격 모두 만족하는 실속 여행이에요", "가격 착하고 이동도 편리해서 부담 없이 가기 좋은 패키지에요",
        "가볍게 떠나기 좋은 가성비+교통 조합이에요"
    ]
}
# -------------------- 챗봇 연동 --------------------
def get_intent_intro_message(intent: str) -> str:
    intent_opening_texts = {
    "쇼핑":"특별한 기념품과 현지의 매력을 느끼고 싶으시군요.",
    "실내": "날씨와 상관없이 알차게 여행을 즐기고 싶으시군요.",
    "가족": "가족과 함께 소중한 추억을 만들고 싶으시군요.",
    "워터파크": "물놀이로 스트레스를 날리고 싶으신가요?",
    "자연": "자연 속에서 힐링하고 싶은 마음이 느껴져요.",
    "전망": "탁 트인 풍경을 바라보며 여유를 느끼고 싶으시군요.",
    "포토존": "잊지 못할 순간을 사진으로 남기고 싶으시군요.",
    "해양체험": "바다 속 세상을 가까이에서 느끼고 싶으신가요?",
    "수족관": "해양 생물을 직접 보고 싶으신가요?",
    "종교": "마음의 평화를 찾고 싶은 여행을 원하시나요?",
    "성당": "아름다운 건축과 고요함을 느끼고 싶으시군요.",
    "예식장": "특별한 순간을 로맨틱하게 남기고 싶으시군요.",
    "커플": "둘만의 로맨틱한 시간을 보내고 싶으시군요.",
    "랜드마크": "도시의 대표 명소에서 그 지역의 매력을 느끼고 싶으시군요.",
    "역사": "과거의 흔적 속에서 깊은 이야기를 느끼고 싶으신가요?",
    "궁전": "왕실의 화려함을 경험하고 싶으시군요.",
    "문화체험": "전통 문화를 직접 체험하고 싶으신가요?",
    "박물관": "새로운 지식과 흥미로운 전시를 경험하고 싶으시군요.",
    "예술감상": "감성과 창의력을 자극하고 싶으시군요.",
    "체험관": "직접 해보는 체험으로 생생한 여행을 원하시나요?",
    "광장": "현지 분위기를 직접 느끼고 싶으시군요.",
    "산책": "여유롭게 걸으며 생각 정리하고 싶으시군요.",
    "미술관": "예술작품 속에서 여유와 영감을 느끼고 싶으시군요",
    "공연": "생생한 무대와 감동을 직접 느끼고 싶으시군요.",
    "유람선": "바다 위에서 낭만적인 시간을 보내고 싶으시군요.",
    "야경": "낮보다 아름다운 밤 풍경을 감상하고 싶으시군요.",
    "이동관광": "편하게 이동하면서 다양한 명소를 보고 싶으시군요.",
    "공원": "잠시 일상을 벗어나 여유를 느끼고 싶으시군요.",
    "도심공원": "도시 속에서 잠깐의 쉼을 원하시나요?",
    "문화거리": "걷기만 해도 감성이 채워지는 골목을 원하시나요?",
    "호수": "잔잔한 풍경 속에서 마음의 평화를 찾고 싶으시군요.",
    "휴양지": "아무 생각 없이 쉬어가고 싶은 순간이시군요.",
    "성": "중세 감성의 고풍스러움을 느끼고 싶으시군요.",
    "관람차": "높은 곳에서 색다른 풍경을 보고 싶으시군요.",
    "테마전시": "독특한 콘텐츠로 새로운 자극을 원하시나요?",
    "강": "물소리를 들으며 여유를 느끼고 싶으시군요.",
    "경기장": "현장의 열기와 박진감을 느끼고 싶으시군요.",
    "사원": "고요한 공간에서 마음을 가라앉히고 싶으시군요.",
    "시장": "현지의 진짜 일상을 경험하고 싶으시군요.",
    "야시장": "밤이 더 매력적인 여행을 기대하고 계시군요.",
    "동물원": "귀여운 친구들을 만나며 힐링하고 싶으시군요.",
    "기차": "천천히 이동하며 풍경을 즐기고 싶으시군요.",
    "항구": "바닷바람과 함께 낭만을 느끼고 싶으시군요.",
    "겨울스포츠": "눈 위에서 짜릿한 활동을 원하시나요?",
    "식물원": "피톤치드향이 가득한 공간에서 편안함을 느끼고 싶으시군요.",
    "케이블카": "색다른 시야로 풍경을 바라보고 싶으시군요.",
    "해변": "햇살과 바다를 함께 즐기고 싶으시군요.",
    "테마파크": "하루종일 웃고 뛰어놀고 싶은 기분이신가요?",
    "트레킹": "자연 속에서 몸과 마음을 걷고 싶으시군요.",
    "섬": "복잡함에서 벗어나 고요함을 찾고 싶으시군요.",
    "미식": "새로운 맛으로 여행의 즐거움을 더하고 싶으시군요.",
    "버스": "편하게 둘러보며 여행하고 싶으시군요.",
    "기념관": "그 시절을 다시 느끼고 싶으신가요?",
    "신사": "신비롭고 조용한 장소를 찾고 계시군요.",
    }
    if intent in intent_opening_texts:
        return intent_opening_texts[intent]
    else:
        raise ValueError(f"의도 '{intent}'에 맞는 문구가 정의되어 있지 않습니다.")

def determine_weather_description_official(row):
    try:
        rain = float(row["강수량"])
        humidity = float(row["습도"])
    except Exception:
        return "날씨 정보 없음"

    if rain >= 10:
        return "비가 많이 오는 날씨예요."
    elif rain >= 3:
        return "비가 오는 날씨예요."
    elif rain >= 0.5:
        return "약한 비가 오는 날씨예요."
    else:
        if humidity >= 85:
            return "흐린 날씨예요."
        elif humidity >= 65:
            return "구름이 많은 날씨예요."
        else:
            return "맑은 날씨예요."

def get_weather_message(city, weather_df, date="2025-06-01"):
    date = pd.to_datetime(date).date()

    # '날짜' 컬럼이 datetime으로 되어있으면 date로 변환
    if pd.api.types.is_datetime64_any_dtype(weather_df["날짜"]):
        weather_df["날짜_일자"] = weather_df["날짜"].dt.date
    else:
        weather_df["날짜_일자"] = pd.to_datetime(weather_df["날짜"], errors="coerce").dt.date

    # 2. 정확 일치 시도
    exact_match = weather_df[
        (weather_df["여행도시"].str.strip() == city.strip())
        & (weather_df["날짜_일자"] == date)
    ]
    if not exact_match.empty:
        row = exact_match.iloc[0]
    else:
        # 3. 포함 검색 시도
        partial_match = weather_df[
            (weather_df["여행도시"].str.contains(city, na=False))
            & (weather_df["날짜_일자"] == date)
        ]
        if not partial_match.empty:
            row = partial_match.iloc[0]
        else:
            return f"📅 {city}의 {date} 날씨 정보가 없습니다."

    # 최고 기온
    try:
        temp = f"{float(row['최고_기온']):.1f}"
        temp_a = f"{float(row['최저_기온']):.1f}°C"
    except Exception:
        temp = "정보 없음"

    # 설명
    desc = determine_weather_description_official(row)

    return f"📅 {row['여행도시']}의 날씨는 {temp}/{temp_a}, {desc}"



def generate_intro_message(intent=None, emotion_groups=None, emotion_scores=None, min_emotion_score=15.0):
    from collections import defaultdict
    import random

    emotion_priority = [
        "감정전환", "위로", "혼란회복", "안정", "편안함", "감탄", "신남", "부정"
    ]

    emotion_messages = {
        "신남": "🎉 즐거움이 가득한 여행을 찾고 계시는군요.",
        "편안함": "😌 고요하고 편안한 여행이 필요하시군요.",
        "안정": "🕊️ 마음의 안정을 찾고 싶으신가 봐요.",
        "감탄": "😍 감동과 놀라움을 느끼고 싶으시군요.",
        "혼란회복": "🌀 마음을 정리할 시간이 필요하신가 봐요.",
        "감정전환": "🔄 기분 전환이 필요한 순간이네요.",
        "위로": "🤍 지친 마음에 작은 위로가 필요하시군요.",
        "부정": "😮 잠시 멈춰 숨 돌릴 시간이 필요하시군요."
    }

    neutral_messages = [
        "지금 이 순간, 어떤 여행이 어울릴지 함께 고민해봤어요.",
        "기분 전환이 필요하신 것 같아요. 여러 스타일의 여행지를 추천드릴게요.",
        "딱 떨어지는 목적은 없지만, 어딘가 떠나고 싶을 때가 있죠.",
        "지금 마음에 맞을 수 있는 여행 스타일 몇 가지를 골라봤어요.",
        "다양한 감정을 담을 수 있는 여행지를 준비했어요.",
        "지금의 기분에 맞춰, 어울릴 만한 여행 스타일을 제안드릴게요."
    ]

    # 👉 사전 오버라이드 결과 우선 적용
    if emotion_groups:
        # 우선순위에 따라 가장 먼저 매칭되는 감정 그룹 메시지를 리턴
        for emo in emotion_priority:
            if emo in emotion_groups:
                return emotion_messages.get(emo, random.choice(neutral_messages))

    # 👉 모델 감정 점수 기반 적용
    group_scores = defaultdict(float)
    if emotion_scores:
        for klue_label, score in emotion_scores:
            group = klue_label_to_group.get(klue_label)
            if group:
                group_scores[group] = max(group_scores[group], score)

    for emo in emotion_priority:
        if emo in group_scores:
            return emotion_messages.get(emo, random.choice(neutral_messages))

    # 👉 아무것도 없으면 중립 메시지
    return random.choice(neutral_messages)

def generate_region_intro(city=None, country=None):# 추가 함############################
    name = city if city else country
    templates = [
        f"✨ 낭만이 가득한 {name}의 매력적인 여행지로 여러분을 초대할게요!",
        f"🌏 {name}에서만 느낄 수 있는 특별한 감성과 순간을 함께 찾아볼까요?",
        f"📍 기억에 오래 남을 {name}의 아름다운 여행지들을 하나하나 소개해드릴게요.",
        f"🌿 {name}에서만 만날수 있는 매력 가득한 여행지를 엄선했어요.",
        f"🎒 일상 속 쉼표가 필요한 지금, {name}에서 설렘 가득한 여정을 떠나보세요."
    ]
    return random.choice(templates)

def parse_companion_and_age(text):
    companions = None
    age_group = None

    # 사용자 입력 ➜ 실제 컬럼명 매핑
    companion_map = {
        "혼자": "나혼자",
        "나혼자": "나혼자",
        "친구": "친구들과",
        "친구들": "친구들과",
        "커플": "커플",
        "연인": "커플",
        "가족": "가족여행",
        "단체": "단체여행"
    }

    # 나이대 매핑 (CSV 컬럼 그대로)
    age_map = {
        "20대": "20대",
        "30대": "30대",
        "40대": "40대",
        "50대": "50대",
        "60대": "60대 이상 ",       
        "60대 이상": "60대 이상 "
    }

    text = text.strip()

    # 동행 파싱
    for k, mapped in companion_map.items():
        if k in text:
            companions = mapped
            break

    # 나이대 파싱
    for k, mapped in age_map.items():
        if k in text:
            age_group = mapped
            break

    # 숫자만 입력했을 때 처리
    if age_group is None:
        if "20" in text:
            age_group = "20대"
        elif "30" in text:
            age_group = "30대"
        elif "40" in text:
            age_group = "40대"
        elif "50" in text:
            age_group = "50대"
        elif "60" in text:
            age_group = "60대 이상 "

    return companions, age_group


#------------------------- 수정
def make_companion_age_message(companions, age_group):
    companion_friendly = {
        "혼자": "혼자",
        "나혼자": "혼자",
        "친구": "친구분들과",
        "친구들과": "친구분들과",
        "커플": "연인과",
        "가족여행": "가족분들과",
        "가족": "가족분들과",
        "단체여행": "단체로",
        "단체": "단체로"
    }

    age_friendly = {
        "20대": "20대",
        "30대": "30대",
        "40대": "40대",
        "50대": "50대",
        "60대 이상": "60대 이상",
        "60대": "60대 이상"
    }
    
    # ✔ 리스트 → 첫 항목(대표값) 또는 None
    def to_friendly(terms, mapping):
        if not terms:
            return []
        if not isinstance(terms, list):
            terms = [terms]
        return [mapping[t] for t in terms if t in mapping]
    
    friendly_ages = to_friendly(age_group, age_friendly)
    friendly_companions = to_friendly(companions, companion_friendly)

    age_text = ", ".join(friendly_ages) + " 여행객" if friendly_ages else ""
    companion_text = ", ".join(friendly_companions)

    if friendly_ages and friendly_companions:
        return f"💡{age_text} {companion_text} 여행하시는 분들께 특히 인기 있는 패키지예요."
    elif friendly_ages:
        return f"💡{age_text} 분들께 인기 있는 패키지예요."
    elif friendly_companions:
        return f"💡{companion_text} 여행하시는 분들께 특히 인기 있는 패키지예요."
    else:
        return ""

#------------------------- 같은 그룹에 2개이상 선택이 가능하도록 로직 수정
def filter_packages_by_companion_age(package_df, companions=None, age_group=None, city=None, top_n=5):
    # 사용자 입력 ➜ 실제 컬럼명 매핑
    companion_map = {
            "혼자": "나혼자",
            "나혼자": "나혼자",
            "친구": "친구들과",
            "친구들": "친구들과",
            "커플": "커플",
            "연인": "커플",
            "가족": "가족여행",
            "단체": "단체여행"
        }

    # 나이대 매핑 (CSV 컬럼 그대로)
    age_map = {
            "20대": "20대",
            "30대": "30대",
            "40대": "40대",
            "50대": "50대",
            "60대": "60대 이상 ",       
            "60대 이상": "60대 이상"
        }

    # companions, age_group → 리스트로 통일
    comp_list = companions if isinstance(companions, list) else ([companions] if companions else [])
    age_list  = age_group  if isinstance(age_group, list)  else ([age_group]  if age_group  else [])

    companions = [companion_map.get(c) for c in comp_list if companion_map.get(c) in package_df.columns]
    age_group  = [age_map.get(a) for a in age_list  if age_map.get(a) in package_df.columns]

    df = package_df.copy()

    # city 컬럼 있으면 필터
    if city and "여행도시" in df.columns:
        df = df[df["여행도시"].str.contains(city, na=False)]

    # 조건1: 동행+연령
    if companions and age_group:
        mask = (df[companions].sum(axis=1) > 0) & (df[age_group].sum(axis=1) > 0)
        both = df[mask].copy()
        if len(both) >= top_n:
            both["점수합"] = both[companions + age_group].sum(axis=1)
            return both.sort_values("점수합", ascending=False).head(top_n)
        
    # 조건2: 연령만
    if age_group:
        age_only = df[df[age_group].sum(axis=1) > 0].copy()
        if len(age_only) >= top_n:
            age_only["점수"] = age_only[age_group].sum(axis=1)
            return age_only.sort_values("점수", ascending=False).head(top_n)
        
    # 조건3: 동행만
    if companions:
        comp_only = df[df[companions].sum(axis=1) > 0].copy()
        if len(comp_only) >= top_n:
            comp_only["점수"] = comp_only[companions].sum(axis=1)
            return comp_only.sort_values("점수", ascending=False).head(top_n)
        
    # 조건4: 아무 조건도 없거나 개수 부족
    return df.sample(n=min(top_n, len(df)))

# -------------------- 핵심 함수 --------------------
def get_highlight_message(selected_place, travel_df, external_score_df, festival_df):
    import random
    from datetime import datetime

    # 메시지 풀
    messages_pool = {
        "festival_score": [
            "🎉 지금 {city}에서는 '{festival_name}'이 진행 중이에요!",
            "🎊 '{festival_name}' 축제가 열리고 있어요! 놓치지 마세요."
        ],
        "cost_score": [
            "💸 여행 비용이 저렴한 편이라 부담 없이 다녀올 수 있어요.",
            "💰 예상 경비가 낮아서 가성비 좋은 여행이 가능합니다."
        ],
        "norm_fx": [
            "💱 환율이 떨어져서 환전하기 좋은 시기예요.",
            "💵 환율이 안정적이라 여행 경비가 절약됩니다.",
            "1,000원으로 더 많은 금액을 환전할 수 있어요!"
        ],
        "norm_cpi": [
            "🛍 현지 물가가 저렴해서 여행 경비가 합리적이에요.",
            "☕ 카페, 식사, 쇼핑까지 부담이 덜해요.",
            "평균보다 낮은 물가 덕분에 여유로운 여행이 가능해요."
        ],
        "트렌드급상승": [
            "📈 최근 검색량이 급등했어요. 요즘 뜨는 여행지예요!",
            "🔥 지금 많은 사람들이 이곳을 검색하고 있어요!"
        ],
        "trend_score": [
            "⭐ 여행객들에게 꾸준히 사랑받고 있는 곳이에요.",
            "✨ 언제 가도 만족도가 높은 인기 여행지예요.",
            "💖 지금도 많은 사람들이 찾는 베스트셀러 여행지예요."
        ]
    }

    # 🎯 축제명 가져오기 함수
    def get_festival_name(city, festival_df):
        today = datetime.today().date()
        matches = festival_df[festival_df["여행도시"] == city]
        if matches.empty:
            return "현지 축제"
        matches = matches.copy()
        try:
            matches["시작일"] = pd.to_datetime(matches["시작일"], errors="coerce").dt.date
            matches["종료일"] = pd.to_datetime(matches["종료일"], errors="coerce").dt.date
        except Exception:
            return "현지 축제"
        # 진행중
        ongoing = matches[(matches["시작일"] <= today) & (matches["종료일"] >= today)]
        if not ongoing.empty:
            return random.choice(ongoing["축제명"].dropna().tolist())
        # 다가오는
        upcoming = matches[matches["시작일"] > today].sort_values("시작일")
        if not upcoming.empty:
            return upcoming.iloc[0]["축제명"]
        return "현지 축제"

    # 🌍 여행지에 해당하는 도시/나라 가져오기
    place_row = travel_df[travel_df["여행지"] == selected_place]
    if place_row.empty:
        return None

    place_row = place_row.iloc[0]
    city = place_row["여행도시"]
    country = place_row["여행나라"]

    # 외부요인 데이터에서 해당 도시/나라 찾기
    external_row = external_score_df[
        (external_score_df["여행도시"] == city) &
        (external_score_df["여행나라"] == country)
    ]
    if external_row.empty:
        return None

    external_row = external_row.iloc[0]

    # 조건별 만족 여부 체크
    highlight_candidates = []

    if external_row.get("festival_score", 0) >= 2:
        festival_name = get_festival_name(city, festival_df)
        if festival_name != '현지 축제':
            msg = random.choice(messages_pool["festival_score"]).format(city=city, festival_name=festival_name)
            highlight_candidates.append(msg)

    if external_row.get("cost_score", 0) == 10:
        highlight_candidates.append(random.choice(messages_pool["cost_score"]))

    if external_row.get("norm_fx", 99) < 1.0:
        highlight_candidates.append(random.choice(messages_pool["norm_fx"]))

    if external_row.get("norm_cpi", 99) < 1.0:
        highlight_candidates.append(random.choice(messages_pool["norm_cpi"]))

    if str(external_row.get("트렌드급상승", "")).strip() == "급상승":
        highlight_candidates.append(random.choice(messages_pool["트렌드급상승"]))

    if external_row.get("trend_score", 0) >= 6.0:
        highlight_candidates.append(random.choice(messages_pool["trend_score"]))

    if not highlight_candidates:
        fallback_messages = [
        "🌿 일상을 벗어나 새로운 경험을 만들어주는, {city}로 떠나보세요.",
        "🎈 뚜렷한 목적 없이도 좋은 기억만 남게 해주는, {city}예요.",
        "🌸 매력이 흘러넘치는 도시, {city}에서 행복한 시간을 보내보세요."
        ]
        return random.choice(fallback_messages).format(city=city)

    # 랜덤 1개만 선택
    return random.choice(highlight_candidates)
    
def apply_weighted_score_random_top(df, top_n=50, sample_k=3):
    # 🛡 원본 백업: 외부 점수 없는 것도 포함된 전체 df
    original_df = df.drop_duplicates(subset=["여행지"]).copy()

    # 외부 점수와 병합
    merged = pd.merge(df, external_score_df, on=["여행도시", "여행나라"], how="left")
    merged["종합점수"] = merged["종합점수"].fillna(0)

    # 상위 점수 정렬
    ranked = merged.sort_values(by="종합점수", ascending=False).drop_duplicates(subset=["여행지"])

    # 최상위 top_n 중 sample_k개 선택
    top_df = ranked.head(top_n)
    top_count = min(sample_k, len(top_df))
    sampled_top = top_df.sample(n=top_count, random_state=random.randint(1, 9999))

    # 부족하면 bottom에서 채우기
    bottom_pool = ranked.iloc[top_n:]
    needed = max(0, 3 - len(sampled_top))
    if needed > 0 and not bottom_pool.empty:
        sampled_bottom = bottom_pool.sample(n=min(needed, len(bottom_pool)), random_state=random.randint(1, 9999))
        final_df = pd.concat([sampled_top, sampled_bottom], ignore_index=True)
    else:
        final_df = sampled_top

    # 🔒 최종 보완: 외부 점수 없던 원본 df에서 무조건 3개 채우기
    if len(final_df) < 3:
        additional = original_df[~original_df["여행지"].isin(final_df["여행지"])]
        if not additional.empty:
            fill_df = additional.sample(n=min(3 - len(final_df), len(additional)), random_state=random.randint(1, 9999))
            final_df = pd.concat([final_df, fill_df], ignore_index=True)

    return final_df
    
def apply_weighted_score_filter(df, top_n=50, sample_k=3):
    return apply_weighted_score_random_top(df, top_n=top_n, sample_k=sample_k)

def override_emotion_if_needed(text):
    for keyword, (emotion_label, emotion_group) in emotion_override_dict.items():
        if keyword in text:
            return [(emotion_label, 50.0)], [emotion_group]
    return None
    
def analyze_emotion(user_input):
    sentiment_model = load_sentiment_model()
    tokenizer = load_tokenizer()
    override = override_emotion_if_needed(user_input)
    if override:
        return override
    inputs = tokenizer(user_input, return_tensors="pt", truncation=True)
    with torch.no_grad():
        probs = F.softmax(sentiment_model(**inputs).logits, dim=1)[0]
    top_indices = torch.topk(probs, k=5).indices.tolist()
    top_emotions = [(klue_emotions[i], float(probs[i]) * 100) for i in top_indices]
    top_emotion_groups = list(dict.fromkeys([klue_to_general[i] for i in top_indices if probs[i] > 0.05]))
    return top_emotions, top_emotion_groups

def detect_intent(user_input):
    force_map = {
        "수족관": "수족관", "아쿠아리움":"수족관", "워터파크": "워터파크", "쇼핑":"쇼핑", "커플":"커플", "실내":"실내", "가족":"가족", "산책":"산책",
        "전망":"전망",  "해양 체험":"해양체험", "종교":"종교", "성당":"성당", "웨딩":"예식장", "역사":"역사", "자연":"자연",
        "궁전":"궁전", "문화 체험": "문화체험", "박물관":"박물관", "예술 작품":"예술감상", "과학관":"체험관", "광장":"광장", "미술관":"미술관",
        "공연":"공연", "유람선":"유람선", "야경":"야경", "호수":"호수", "휴양지":"휴양지","관람차":"관람차", "강":"강",
        "경기장":"경기장", "사원":"사원", "시장":"시장", "야시장":"야시장", "동물원":"동물원", "기차":"기차", "항구":"항구", "겨울 스포츠":"겨울스포츠",
        "식물원":"식물원", "케이블카":"케이블카", "해변":"해변", "바다":"해변", "테마파크":"테마파크", "트레킹":"트레킹", "섬":"섬", "맛있는":"미식", 
        "버스":"버스", "기념관":"기념관", "신사":"신사", '바다':'해변', '인생샷':'포토존','먹방':'미식','소품':'쇼핑','바닷가':'해변','서핑':'해양체험',
        '일몰':'전망','로맨틱':'커플','브랜드샵':'쇼핑','아울렛':'쇼핑','비치':'해변','고성':'성','고궁':'궁전','문화거리':'문화거리','전통마을':'문화체험',
        '곤돌라':'케이블카','스카이라인':'전망','힐링':'휴양지', '미식':'쇼핑', '문화':'문화체험', '걷기':'산책'
    }
    for keyword, mapped_intent in force_map.items():
        if keyword in user_input:
            return mapped_intent, 1.0
    phrases, labels = [], []
    for intent, keywords in intent_keywords.items():
        for word in keywords:
            phrases.append(word)
            labels.append(intent)

    sbert_model = load_sbert_model()
    input_emb = sbert_model.encode(user_input, convert_to_tensor=True)
    phrase_embs = sbert_model.encode(phrases, convert_to_tensor=True)
    sims = util.cos_sim(input_emb, phrase_embs)[0]
    max_idx = torch.argmax(sims).item()
    return labels[max_idx], float(sims[max_idx])

def extract_themes(emotion_groups, intent, force_mode=False):
    scores = defaultdict(float)
    if force_mode:
        mapped = category_mapping.get(intent)
        if mapped:
            scores[mapped] += 1.0
        return list(scores.keys())[:3]
    for group in emotion_groups:
        for cat in emotion_to_category_boost.get(group, []):
            mapped = category_mapping.get(cat)
            if mapped:
                scores[mapped] += 1.0
    mapped = category_mapping.get(intent)
    if mapped:
        scores[mapped] += 1.5
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    
    return [x[0] for x in ranked[:3]]


def recommend_places_by_theme(theme, country_filter=None, city_filter=None):
    today = datetime.today().date()
    
    # 1. 테마 필터링
    df = travel_df[travel_df['의도테마명'].str.contains(theme, na=False)].drop_duplicates(subset=["여행지"])

    # 2. 국가/도시 필터링
    if city_filter:
        df = df[df["여행도시"].str.contains(city_filter)]
    if country_filter:
        df = df[df["여행나라"].str.contains(country_filter)]

    # 3. 비어있으면 빈 DF 리턴
    if df.empty:
        df = pd.DataFrame(columns=travel_df.columns)  # 빈 DF라도 컬럼 포함

    # ✅ 최소 3개 수집 보장
    collected = df.copy()

    extra_fill = travel_df[
        (travel_df['의도테마명'].str.contains(theme, na=False)) &
        (~travel_df['여행지'].isin(collected['여행지']))
    ].drop_duplicates(subset=["여행지"])

    needed = 3 - len(collected)
    if needed > 0 and not extra_fill.empty:
        fill = extra_fill.sample(n=min(needed, len(extra_fill)), random_state=random.randint(1, 9999))
        collected = pd.concat([collected, fill], ignore_index=True)

    # 여전히 부족하면 무작위로 travel_df에서 채우기
    if len(collected) < 3:
        fallback = travel_df[~travel_df['여행지'].isin(collected['여행지'])].drop_duplicates(subset=["여행지"])
        if not fallback.empty:
            fill = fallback.sample(n=min(3 - len(collected), len(fallback)), random_state=random.randint(1, 9999))
            collected = pd.concat([collected, fill], ignore_index=True)

    # ✅ 필수 컬럼 보장
    for col in ["여행도시", "여행나라"]:
        if col not in collected.columns:
            collected[col] = None

    # ✅ 통합테마명 보장
    if "통합테마명" not in collected.columns:
        collected["통합테마명"] = theme
    else:
        collected["통합테마명"] = collected["통합테마명"].fillna(theme)

    return collected

    def get_festival_info(city):
        match = festival_df[festival_df['여행도시'] == city]
        if match.empty:
            return "없음", None, None
        row = match.iloc[0]
        try:
            start = pd.to_datetime(row["시작일"]).date()
            end = pd.to_datetime(row["종료일"]).date()
            if end < today:
                return "없음", None, None
            return row["축제명"], start, end
        except:
            return "없음", None, None
    df[["추천축제", "축제시작", "축제종료"]] = df["여행도시"].apply(lambda x: pd.Series(get_festival_info(x)))
    return df

def make_top2_description_custom(row, used_phrases=set()):
        scores = {
            k: row.get(k, 0)
            for k in ["숙소", "일정", "가이드", "식사", "가성비", "이동수단"]
        }
        top2 = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:2]
        top2_keys = frozenset([k for k, _ in top2])
        phrases = feature_phrase_map.get(top2_keys, [])

        if not phrases:
            return "", used_phrases

        available = [p for p in phrases if p not in used_phrases]
        phrase = random.choice(available) if available else random.choice(phrases)
        used_phrases.add(phrase)
        return phrase, used_phrases

def format_summary_tags_custom(summary):
    if pd.isna(summary):
        return ""
    parts = [s.strip() for s in summary.split(",") if s.strip()]
    tags = []

    i = 0
    while i < len(parts):
        part = parts[i]
        # 가이드 경비 블록 처리
        if "가이드 경비" in part or "가이드경비" in part:
            guide_block = [part]
            j = i + 1
            while j < len(parts):
                next_part = parts[j]
                guide_block.append(next_part)
                if "선택관광" in next_part:
                    break
                j += 1

            if len(guide_block) > 1:
                merged = "".join(guide_block[:-1]).replace(" ", "")
                tags.append(f"#{merged}")
                tags.append(f"#{guide_block[-1].strip()}")
            else:
                tags.extend(f"#{x.strip()}" for x in guide_block)

            i = j + 1
            continue

        # 일반 항목
        tags.append(f"#{part}")
        i += 1

    return " ".join(tags)

def recommend_packages(
    selected_theme,
    selected_place,
    travel_df,
    package_df,
    theme_ui_map,
    chat_container=None
):
    import random

    # ✅ 통합 테마명 추출
    if selected_theme in theme_ui_map:
        integrated_theme = selected_theme
    else:
        integrated_theme = (
            travel_df[
                travel_df["의도테마명"].str.contains(selected_theme, na=False)
            ]
            .drop_duplicates(subset=["여행지"])["통합테마명"]
            .mode()
            .iloc[0]
        )

    # ✅ UI 이름 및 도시명
    selected_ui_name = theme_ui_map[integrated_theme][0]
    selected_city = travel_df.loc[
        travel_df["여행지"] == selected_place, "여행도시"
    ].values[0]

    # ✅ 도시 필터
    filtered_package = package_df[
        package_df["여행도시"].str.contains(selected_city, na=False)
    ].copy()

    # 📝 감성 문구
    def make_top2_description(row, used_phrases=set()):
        scores = {
            k: row.get(k, 0)
            for k in ["숙소", "일정", "가이드", "식사", "가성비", "이동수단"]
        }
        top2 = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:2]
        top2_keys = frozenset([k for k, _ in top2])
        phrases = feature_phrase_map.get(top2_keys, [])

        if not phrases:
            return "", used_phrases

        available = [p for p in phrases if p not in used_phrases]
        phrase = random.choice(available) if available else random.choice(phrases)
        used_phrases.add(phrase)
        return phrase, used_phrases

    # 📝 요약정보를 해시태그로 변환
    def format_summary_tags(summary):
        if pd.isna(summary):
            return ""
        parts = [s.strip() for s in summary.split(",") if s.strip()]
        tags = []

        i = 0
        while i < len(parts):
            part = parts[i]
            # 가이드 경비 블록 처리
            if "가이드 경비" in part or "가이드경비" in part:
                guide_block = [part]
                j = i + 1
                while j < len(parts):
                    next_part = parts[j]
                    guide_block.append(next_part)
                    if "선택관광" in next_part:
                        break
                    j += 1

                if len(guide_block) > 1:
                    merged = "".join(guide_block[:-1]).replace(" ", "")
                    tags.append(f"#{merged}")
                    tags.append(f"#{guide_block[-1].strip()}")
                else:
                    tags.extend(f"#{x.strip()}" for x in guide_block)

                i = j + 1
                continue

            # 일반 항목
            tags.append(f"#{part}")
            i += 1

        return " ".join(tags)

    # ✅ 샘플링
    recommend_package = filtered_package.sample(
        n=min(2, len(filtered_package)),
        random_state=42
    )

    # ✅ 문구 생성
    recommend_texts = []
    title_candidates = theme_title_phrases.get(selected_ui_name, ["추천"])
    sampled_titles = random.sample(title_candidates, k=min(2, len(title_candidates)))
    
    used_phrases = set()
    for idx, (_, row) in enumerate(recommend_package.iterrows(), 1):
        desc, used_phrases = make_top2_description(row.to_dict(), used_phrases)
        tags = format_summary_tags(row["요약정보"])
        title_phrase = sampled_titles[idx - 1] if idx <= len(sampled_titles) else random.choice(title_candidates)
        title = f"{selected_city} {title_phrase} 패키지"

        recommend_texts.append(
            f"""{idx}. <strong>{title}</strong><br> 🅼 {desc}<br>  {tags}<br> \
               <a href="{row.URL}" target="_blank" rel="noopener noreferrer"
           style="text-decoration:none;font-weight:600;color:#009c75;">
           💚 바로가기&nbsp;↗
        </a>"""
        )

    # ✅ 출력
    if recommend_texts:
        full_message = "🧳 이런 패키지를 추천드려요:<br><br>" + "<br><br>".join(recommend_texts)
        log_and_render(
            full_message,
            sender="bot",
            chat_container = chat_container,
            key="recommend_package_intro",
    )
    else:
        log_and_render(
            "⚠️ 추천 가능한 패키지가 없습니다.",
            sender="bot",
            chat_container = chat_container,
            key="no_package_warning"
    )
        return
        
def handle_selected_place(selected_place, travel_df, external_score_df, festival_df, weather_df, selected_theme=None, chat_container=None):
    selected_row = travel_df[travel_df["여행지"] == selected_place].iloc[0]
    country = selected_row["여행나라"]
    city = selected_row["여행도시"]

    message_lines = []
    message_lines.append(f"{selected_place}은(는) {city}에 위치해 있어요.")
    message_lines.append(get_weather_message(city, weather_df))

    highlight = get_highlight_message(selected_place, travel_df, external_score_df, festival_df)
    if highlight:
        message_lines.append(highlight+"<br>")

    ##수정##
    other = travel_df[(travel_df["여행도시"] == city) & (travel_df["여행지"] != selected_place)].drop_duplicates("여행지")
    if not other.empty:
        other_sample = other.sample(n=min(3, len(other)), random_state=42)
        sample_names = ", ".join(other_sample["여행지"].tolist())
        message_lines.append(f"함께 가보면 좋은 여행지: {sample_names}")
    else:
        message_lines.append("⚠️ 함께 가볼 다른 여행지가 없어요.")
    # integrated_theme 추론 추가
    if selected_theme is None:
        theme_row = travel_df[travel_df["여행지"] == selected_place]
        if not theme_row.empty and pd.notna(theme_row.iloc[0]["통합테마명"]):
            selected_theme = theme_row.iloc[0]["통합테마명"]

    full_message = "<br>".join(message_lines)

    log_and_render(
        full_message,
        sender="bot",
        key=f"region_detail_{selected_place}",
        chat_container=chat_container
    )

    recommend_packages(
        selected_theme=selected_theme,
        selected_place=selected_place,
        travel_df=travel_df,
        package_df=package_df,
        theme_ui_map=theme_ui_map,
        chat_container=chat_container
    )

def main():
    user_input = input("요즘, 어떤 여행이 떠오르시나요?")

    # 1. 감정 및 의도 분석
    top_emotions, emotion_groups = analyze_emotion(user_input)
    intent, intent_score = detect_intent(user_input)
    country_filter, city_filter = detect_location_filter(user_input)

    if country_filter or city_filter:
        loc_str = f"{country_filter or ''} {city_filter or ''}".strip()
        print(f"🔎 '{city_filter or country_filter}'에 해당하는 여행지들만 기반으로 추천드릴게요!")
        
    candidate_themes = extract_themes(emotion_groups, intent, force_mode=(intent_score >= 0.7))

    # 2. 출력
    print("\n[감정 분석 결과]")
    for emo, score in top_emotions:
        print(f"- {emo}: {score:.2f}%")
    print(f"\n[의도 판단 결과] → {intent} (유사도: {intent_score:.2f})")

    # 3. 조건 분기

    # ✅ case 1: intent 기반 추천
    if intent_score >= 0.70:
        selected_theme = intent
        print(f"\n[명확한 의도에 따라 자동 추천 테마 선택됨] → {selected_theme}")
        
        # 의도 오프닝 문구 출력
        ui_name = theme_ui_map.get(selected_theme, (selected_theme,))[0]
        opening_line = (
            theme_opening_lines.get(ui_name)
            or intent_opening_lines.get(selected_theme)
            or None
        )
        if opening_line:
            print(f"\n{opening_line}")
    
        theme_df = recommend_places_by_theme(selected_theme, country_filter, city_filter)
        theme_df = theme_df.drop_duplicates(subset=["여행지"])
        result_df = apply_weighted_score_filter(theme_df)
        
        if len(result_df) < 3:            
            fallback = travel_df[~travel_df['여행지'].isin(result_df['여행지'])].drop_duplicates(subset=["여행지"])
            if not fallback.empty:
                fill = fallback.sample(n=min(3 - len(result_df), len(fallback)), random_state=random.randint(1, 9999))
                result_df = pd.concat([result_df, fill], ignore_index=True)
                
    # ✅ case 2: 후보 테마가 1개
    elif len(candidate_themes) == 1:
        selected_theme = candidate_themes[0]
        print(f"\n추천 가능한 테마가 1개이므로 자동 선택: {selected_theme}")
        theme_df = recommend_places_by_theme(selected_theme, country_filter, city_filter)
        theme_df = theme_df.drop_duplicates(subset=["여행지"])
        result_df = apply_weighted_score_filter(theme_df)

        if len(result_df) < 3:            
            fallback = travel_df[~travel_df['여행지'].isin(result_df['여행지'])].drop_duplicates(subset=["여행지"])
            if not fallback.empty:
                fill = fallback.sample(n=min(3 - len(result_df), len(fallback)), random_state=random.randint(1, 9999))
                result_df = pd.concat([result_df, fill], ignore_index=True)
                
    # ✅ case 3: 복수 테마 → 사용자 선택
    else:
        # 복수 테마의 여행지 전체 수집
        all_theme_df = pd.concat([
            recommend_places_by_theme(t, country_filter, city_filter) for t in candidate_themes
        ])
        all_theme_df = all_theme_df.drop_duplicates(subset=["여행지"])

        # 통합테마명 목록 추출
        # 5. 최종 병합
        filtered = pd.merge(
            all_theme_df,
            external_score_df[["여행나라", "여행도시"]],
            on=["여행나라", "여행도시"],
            how="inner"
        ).drop_duplicates(subset=["여행지"])

        # 2) 중복 제거 후 최종 테마 목록
        filtered = filtered.drop_duplicates(subset=['여행지'])
        available_themes = filtered['통합테마명'].dropna().unique().tolist()[:3] ##[:3] 가가
        
        # 💡 감성 UI 포맷으로 출력
        print("\n추천 가능한 여행 테마:")
        for idx, theme in enumerate(available_themes, 1):
            ui_name, ui_desc = theme_ui_map.get(theme, (theme, ""))
            print(f"{idx}. {ui_name} – {ui_desc}")
        
        print("\n👉 어떤 테마가 끌리시나요?")
        print(" ".join(f"[{theme_ui_map.get(t, (t,))[0]}]" for t in available_themes))
        
        # 자동 선택 or 사용자 입력
        if len(available_themes) == 1:
            selected_ui_name = theme_ui_map.get(available_themes[0], (available_themes[0], ""))[0]
            selected_theme = ui_to_theme_map[selected_ui_name]
            print(f"\n추천 가능한 테마가 1개이므로 자동 선택: {selected_ui_name}")
        else:
            sel = int(input("\n원하는 테마 번호를 선택하세요: ")) - 1
            selected_ui_name = theme_ui_map.get(available_themes[sel], (available_themes[sel], ""))[0]
            selected_theme = ui_to_theme_map[selected_ui_name]
            print(f"\n선택하신 테마: {selected_ui_name}")

        # 해당 테마 기준 최종 추천
        theme_df = all_theme_df[all_theme_df["통합테마명"] == selected_theme]
        theme_df = theme_df.drop_duplicates(subset=["여행지"])
        result_df = apply_weighted_score_filter(theme_df)

        ###추가###
        if len(result_df) < 3:            
            fallback = travel_df[~travel_df['여행지'].isin(result_df['여행지'])].drop_duplicates(subset=["여행지"])
            if not fallback.empty:
                fill = fallback.sample(n=min(3 - len(result_df), len(fallback)), random_state=random.randint(1, 9999))
                result_df = pd.concat([result_df, fill], ignore_index=True)
        
    # 4. 결과 출력
    if intent_score < 0.7:  # 감정 기반인 경우에만 출력
        ui_name = theme_ui_map.get(selected_theme, (selected_theme,))[0]
        opening_line_template = theme_opening_lines.get(ui_name)
        if opening_line_template:
            print(f"\n{opening_line_template.format(len(result_df))}")
    
    print("\n[최종 추천 여행지]")
    for idx, row in enumerate(result_df.itertuples(), 1):
        country = row.여행나라
        city = row.여행도시
        name = row.여행지
        desc = row.한줄설명 if hasattr(row, '한줄설명') else "설명이 없습니다"

        if country == city:
            loc = f"{country}"
        else:
            loc = f"{country}, {city}"

        print(f"{idx}. {name} ({loc}) - {desc}")

    recommend_names = result_df["여행지"].tolist()

    print("\n👉 마음에 드는 여행지를 골라주세요:")
    print(" ".join(f"[{name}]" for name in recommend_names))
        
    try:
        sel = int(input("\n원하는 여행지 번호를 선택하세요:")) - 1
        if 0 <= sel < len(recommend_names):
            selected_place = recommend_names[sel]
            print(f"\n🎉 '{selected_place}'를 선택하셨습니다. 멋진 여행 되세요!")
        else:
            print("\n⚠️ 올바른 번호를 입력해주세요.")
    except ValueError:
        print("\n⚠️ 숫자로 된 번호를 입력해주세요.")

# In[12]:


# if __name__ == "__main__":
#main()


# In[ ]:




