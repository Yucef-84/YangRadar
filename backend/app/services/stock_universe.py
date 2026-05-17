from __future__ import annotations


LOCAL_STOCKS = [
    {"code": "005930", "name": "삼성전자", "market": "KOSPI", "sector": "전기전자", "listed_shares": 5969782550},
    {"code": "000660", "name": "SK하이닉스", "market": "KOSPI", "sector": "반도체", "listed_shares": 728002365},
    {"code": "005380", "name": "현대차", "market": "KOSPI", "sector": "운수장비", "listed_shares": 211531506},
    {"code": "000270", "name": "기아", "market": "KOSPI", "sector": "운수장비", "listed_shares": 402044203},
    {"code": "035420", "name": "NAVER", "market": "KOSPI", "sector": "서비스업", "listed_shares": 164049085},
    {"code": "035720", "name": "카카오", "market": "KOSPI", "sector": "서비스업", "listed_shares": 445905990},
    {"code": "051910", "name": "LG화학", "market": "KOSPI", "sector": "화학", "listed_shares": 70592343},
    {"code": "373220", "name": "LG에너지솔루션", "market": "KOSPI", "sector": "전기전자", "listed_shares": 234000000},
    {"code": "006400", "name": "삼성SDI", "market": "KOSPI", "sector": "전기전자", "listed_shares": 68764530},
    {"code": "068270", "name": "셀트리온", "market": "KOSPI", "sector": "의약품", "listed_shares": 220290520},
    {"code": "207940", "name": "삼성바이오로직스", "market": "KOSPI", "sector": "의약품", "listed_shares": 71174000},
    {"code": "005490", "name": "POSCO홀딩스", "market": "KOSPI", "sector": "철강금속", "listed_shares": 84571230},
    {"code": "105560", "name": "KB금융", "market": "KOSPI", "sector": "금융업", "listed_shares": 403511072},
    {"code": "055550", "name": "신한지주", "market": "KOSPI", "sector": "금융업", "listed_shares": 511005290},
    {"code": "086790", "name": "하나금융지주", "market": "KOSPI", "sector": "금융업", "listed_shares": 292356598},
    {"code": "316140", "name": "우리금융지주", "market": "KOSPI", "sector": "금융업", "listed_shares": 751949461},
    {"code": "012450", "name": "한화에어로스페이스", "market": "KOSPI", "sector": "운수장비", "listed_shares": 50630000},
    {"code": "034020", "name": "두산에너빌리티", "market": "KOSPI", "sector": "기계", "listed_shares": 640561146},
    {"code": "003670", "name": "포스코퓨처엠", "market": "KOSPI", "sector": "전기전자", "listed_shares": 77463220},
    {"code": "247540", "name": "에코프로비엠", "market": "KOSDAQ", "sector": "일반전기전자", "listed_shares": 97801344},
    {"code": "086520", "name": "에코프로", "market": "KOSDAQ", "sector": "금융", "listed_shares": 26627518},
    {"code": "028300", "name": "HLB", "market": "KOSDAQ", "sector": "제약", "listed_shares": 131170623},
    {"code": "196170", "name": "알테오젠", "market": "KOSDAQ", "sector": "제약", "listed_shares": 53011128},
    {"code": "277810", "name": "레인보우로보틱스", "market": "KOSDAQ", "sector": "기계장비", "listed_shares": 19455640},
    {"code": "125490", "name": "한라캐스트", "market": "KOSDAQ", "sector": "금속/부품", "listed_shares": 36562000},
]


def local_stock(code: str) -> dict:
    return next(
        (stock for stock in LOCAL_STOCKS if stock["code"] == code),
        {"code": code, "name": code, "market": "UNKNOWN", "sector": "정보 없음", "listed_shares": None},
    )

