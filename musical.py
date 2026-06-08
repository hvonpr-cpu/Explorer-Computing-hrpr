
# ========================================================================================
# 1. 기본 설정
# ========================================================================================


# 라이브러리 불러오기
import streamlit as st
import pandas as pd
import calendar
import html
import requests
import re
import time
from bs4 import BeautifulSoup
from datetime import date
import os
from selenium.webdriver.chrome.service import Service
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoAlertPresentException,
    StaleElementReferenceException
)


# 페이지 설정
st.set_page_config(page_title="회전문 빙글빙글", page_icon="🎵", layout="wide")


# ========================================================================================
# 2. 기본 데이터 구조
# ========================================================================================


DEFAULT_DISCOUNT_TEXT = "할인 없음,0\n조기예매 할인,20\n재관람 할인,30"


def default_musical_info():
    default_stamp_benefits = [
        {"at": 3, "name": "50% 할인 쿠폰"},
        {"at": 7, "name": "굿즈/실황 쿠폰"}
    ]

    return {
        "seat_prices": {
            "R석": 0,
            "S석": 0
        },
        "discount_rules": {
            "할인 없음": 0,
            "조기예매 할인": 20,
            "재관람 할인": 30
        },
        "stamp_benefits": default_stamp_benefits,
        "coupons": {
            benefit["name"]: 0 for benefit in default_stamp_benefits
        }
    }


# ========================================================================================
# 3. NOL 티켓 좌석 가격 자동 수집
# ========================================================================================

def extract_seat_prices_from_soup(soup):
    seat_prices = {}

    items = soup.select("ul.infoPriceList li.infoPriceItem, li.infoPriceItem")

    for item in items:
        name_tag = item.select_one("span.name")
        price_tag = item.select_one("span.price")

        if name_tag is None or price_tag is None:
            continue

        seat = name_tag.get_text(strip=True)
        price_text = price_tag.get_text("", strip=True)
        price_number = re.sub(r"[^0-9]", "", price_text)

        if seat and price_number:
            seat_prices[seat] = int(price_number)

    if len(seat_prices) == 0:
        rows = soup.select("table.popPriceTable tbody tr, table.popPriceTable tr")

        current_seat = None

        for row in rows:
            category_tag = row.select_one("td.category span.categoryContents")

            if category_tag is not None:
                current_seat = category_tag.get_text(strip=True)

            name_tag = row.select_one("td.name")
            cells = row.find_all("td")

            if current_seat is None or name_tag is None or len(cells) == 0:
                continue

            name_text = name_tag.get_text(" ", strip=True)
            price_text = cells[-1].get_text(" ", strip=True)

            if "일반" in name_text:
                price_number = re.sub(r"[^0-9]", "", price_text)

                if price_number:
                    seat_prices[current_seat] = int(price_number)

    return seat_prices


def extract_seat_prices_from_text(text):
    seat_prices = {}

    pattern = r"(VIP석|OP석|R석|S석|A석|B석|C석|전석)\s*[:：]?\s*(?:일반)?\s*([0-9,]+)\s*원"
    matches = re.findall(pattern, text)

    for seat, price in matches:
        seat_prices[seat] = int(price.replace(",", ""))

    return seat_prices


def extract_seat_prices_from_driver_text(driver, debug_logs=None):
    if debug_logs is None:
        debug_logs = []

    seat_names = ["VIP석", "OP석", "R석", "S석", "A석", "B석", "C석", "전석"]

    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(1)

    last_body_text = ""

    for i in range(18):
        body_text = driver.find_element(By.TAG_NAME, "body").text
        last_body_text = body_text

        if ("R석" in body_text or "S석" in body_text or "VIP석" in body_text or "전석" in body_text) and "원" in body_text:
            break

        driver.execute_script("window.scrollBy(0, 700);")
        time.sleep(0.7)

    body_text = last_body_text

    candidate_texts = []

    for seat in seat_names:
        elems = driver.find_elements(
            By.XPATH,
            f"//*[contains(normalize-space(), '{seat}')]"
        )

        for elem in elems:
            try:
                current = elem

                for depth in range(8):
                    text = current.text.strip()

                    if seat in text and "원" in text:
                        if text not in candidate_texts:
                            candidate_texts.append(text)
                        break

                    current = current.find_element(By.XPATH, "..")

            except Exception:
                pass

    all_text = "\n".join(candidate_texts)

    if not all_text.strip():
        all_text = body_text

    seat_prices = {}

    price_pattern = r"(VIP석|OP석|R석|S석|A석|B석|C석|전석)\s*[\n\r\t ]*(?:일반\s*)?[\n\r\t ]*([0-9]{1,3}(?:,[0-9]{3})*)\s*원"
    prices = re.findall(price_pattern, all_text)

    for seat, price in prices:
        seat_prices[seat] = int(price.replace(",", ""))

    return seat_prices


def make_chrome_options(headless=True):
    options = Options()

    if os.path.exists("/usr/bin/chromium"):
        options.binary_location = "/usr/bin/chromium"
    elif os.path.exists("/usr/bin/chromium-browser"):
        options.binary_location = "/usr/bin/chromium-browser"

    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--log-level=3")

    options.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    )

    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    return options


def create_chrome_driver(headless=True):
    chrome_options = make_chrome_options(headless=headless)

    if os.path.exists("/usr/bin/chromedriver"):
        service = Service("/usr/bin/chromedriver")
        return webdriver.Chrome(service=service, options=chrome_options)

    return webdriver.Chrome(options=chrome_options)


def apply_stealth(driver):
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            """
        }
    )


def fetch_seat_prices_with_selenium(url):
    seat_prices = {}
    driver = None
    debug_logs = []

    try:
        driver = create_chrome_driver(headless=True)
        apply_stealth(driver)

        driver.get(url)

        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        time.sleep(5)

        try:
            alert = driver.switch_to.alert
            alert.accept()
            return {}
        except NoAlertPresentException:
            pass

        if "/goods/" not in driver.current_url:
            return {}

        soup = BeautifulSoup(driver.page_source, "html.parser")
        seat_prices = extract_seat_prices_from_soup(soup)

        if len(seat_prices) == 0:
            seat_prices = extract_seat_prices_from_driver_text(driver, debug_logs)

        if len(seat_prices) == 0:
            body_text = driver.find_element(By.TAG_NAME, "body").text
            seat_prices = extract_seat_prices_from_text(body_text)

    except Exception:
        seat_prices = {}

    finally:
        if driver is not None:
            driver.quit()

    return seat_prices


def fetch_musical_info_from_url(url):
    headers = {"User-Agent": "Mozilla/5.0"}

    seat_prices = {}
    success = False
    error_message = ""

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text(" ", strip=True)

        seat_prices = extract_seat_prices_from_soup(soup)

        if len(seat_prices) == 0:
            seat_prices = extract_seat_prices_from_text(text)

        success = True

    except Exception as e:
        error_message = str(e)

    if len(seat_prices) == 0:
        selenium_prices = fetch_seat_prices_with_selenium(url)

        if len(selenium_prices) > 0:
            seat_prices = selenium_prices
            success = True

    default_info = default_musical_info()

    return {
        "success": success,
        "error": error_message,
        "seat_prices": seat_prices,
        "discount_rules": default_info["discount_rules"].copy(),
        "stamp_benefits": default_info["stamp_benefits"].copy()
    }


def fetch_musical_info_from_nol_search(search_word):
    default_info = default_musical_info()
    debug_logs = []

    result = {
        "success": False,
        "error": "",
        "seat_prices": {},
        "discount_rules": default_info["discount_rules"].copy(),
        "stamp_benefits": default_info["stamp_benefits"].copy(),
        "detail_url": ""
    }

    driver = None

    try:
        driver = create_chrome_driver(headless=True)
        wait = WebDriverWait(driver, 20)
        apply_stealth(driver)

        driver.get("https://nol.interpark.com/")
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))

        search_success = False

        search_locators = [
            (By.CLASS_NAME, "_marketing-text-field_n9y8c_13"),
            (By.CSS_SELECTOR, "input[class*='marketing-text-field']"),
            (By.CSS_SELECTOR, "input[placeholder*='검색']"),
            (By.CSS_SELECTOR, "input[type='search']"),
            (By.CSS_SELECTOR, "header form input"),
            (By.CSS_SELECTOR, "form input")
        ]

        for locator in search_locators:
            try:
                box_elem = wait.until(
                    EC.presence_of_element_located(locator)
                )

                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});",
                    box_elem
                )
                time.sleep(0.3)

                try:
                    box_elem.click()
                    time.sleep(0.3)
                    box_elem.clear()
                    box_elem.send_keys(search_word)

                except Exception:
                    driver.execute_script(
                        """
                        arguments[0].value = arguments[1];
                        arguments[0].dispatchEvent(new Event('input', { bubbles: true }));
                        arguments[0].dispatchEvent(new Event('change', { bubbles: true }));
                        """,
                        box_elem,
                        search_word
                    )

                search_success = True
                break

            except (TimeoutException, StaleElementReferenceException):
                time.sleep(0.5)

        if not search_success:
            result["error"] = "검색창에 검색어를 입력하지 못했습니다."
            return result

        search_button_xpath = '//*[@id="interparkMainWrap"]/header[2]/div/div/div[1]/form/button'

        search_button = wait.until(
            EC.element_to_be_clickable((By.XPATH, search_button_xpath))
        )

        search_button.click()

        time.sleep(3)

        first_result = None

        result_locators = [
            (By.XPATH, '//*[@id="SearchContainer"]/div/div/div[2]/div[1]/div/div/li/a'),
            (By.CSS_SELECTOR, "#SearchContainer a[href*='/goods/']"),
            (By.CSS_SELECTOR, "a[href*='tickets.interpark.com/goods/']"),
            (By.CSS_SELECTOR, "a[href*='/goods/']")
        ]

        for locator in result_locators:
            try:
                elems = wait.until(
                    EC.presence_of_all_elements_located(locator)
                )

                if elems:
                    first_result = elems[0]
                    break

            except TimeoutException:
                pass

        if first_result is None:
            result["error"] = "검색 결과를 찾지 못했습니다."
            return result

        old_windows = driver.window_handles
        old_url = driver.current_url

        try:
            driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});",
                first_result
            )
            time.sleep(0.5)
            driver.execute_script("arguments[0].click();", first_result)

        except StaleElementReferenceException:
            first_result = wait.until(
                EC.element_to_be_clickable(
                    (By.XPATH, '//*[@id="SearchContainer"]/div/div/div[2]/div[1]/div/div/li/a')
                )
            )

            driver.execute_script("arguments[0].click();", first_result)

        try:
            wait.until(
                lambda d: len(d.window_handles) > len(old_windows) or d.current_url != old_url
            )

        except TimeoutException:
            pass

        if len(driver.window_handles) > len(old_windows):
            new_window = [w for w in driver.window_handles if w not in old_windows][0]
            driver.switch_to.window(new_window)

        time.sleep(2)

        try:
            alert = driver.switch_to.alert
            alert_text = alert.text
            alert.accept()
            time.sleep(1)

            result["error"] = f"상세 페이지 진입 중 alert 발생: {alert_text}"
            result["detail_url"] = driver.current_url
            return result

        except NoAlertPresentException:
            pass

        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(5)

        result["detail_url"] = driver.current_url

        if "/goods/" not in driver.current_url:
            result["error"] = "상품 상세 페이지가 아니라 다른 페이지로 이동했습니다."
            return result

        body_text = driver.find_element(By.TAG_NAME, "body").text

        seat_prices = extract_seat_prices_from_driver_text(driver, debug_logs)

        if len(seat_prices) == 0:
            soup = BeautifulSoup(driver.page_source, "html.parser")
            seat_prices = extract_seat_prices_from_soup(soup)

        if len(seat_prices) == 0:
            seat_prices = extract_seat_prices_from_text(body_text)

        result["seat_prices"] = seat_prices

        if len(seat_prices) > 0:
            result["success"] = True

        else:
            result["success"] = False
            result["error"] = "검색과 상세 페이지 진입은 됐지만 좌석 가격을 찾지 못했습니다."

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"

    finally:
        if driver is not None:
            driver.quit()

    return result


# ========================================================================================
# 4. 입력값 변환 및 스키마 보정
# ========================================================================================

def seat_prices_to_text(seat_prices):
    lines = []

    for seat, price in seat_prices.items():
        lines.append(f"{seat},{price}")

    return "\n".join(lines)


def parse_seat_prices_text(text):
    seat_prices = {}

    for line in text.splitlines():
        line = line.strip()

        if line == "":
            continue

        match = re.match(r"(.+?)[,，]\s*([0-9,]+)\s*$", line)

        if match is None:
            continue

        seat = match.group(1).strip()
        price = int(match.group(2).replace(",", ""))

        seat_prices[seat] = price

    return seat_prices


def discount_rules_to_text(discount_rules):
    lines = []

    for name, rate in discount_rules.items():
        lines.append(f"{name},{rate}")

    return "\n".join(lines)


def parse_discount_rules_text(text):
    discount_rules = {}

    for line in text.splitlines():
        line = line.strip()

        if line == "":
            continue

        match = re.match(r"(.+?)[,，]\s*([0-9]{1,3})\s*$", line)

        if match is None:
            continue

        name = match.group(1).strip()
        rate = int(match.group(2))

        if 0 <= rate <= 100:
            discount_rules[name] = rate

    return discount_rules


def stamp_benefits_to_text(stamp_benefits):
    lines = []

    for benefit in stamp_benefits:
        at = benefit.get("at", 0)
        name = benefit.get("name", "")

        if at and name:
            lines.append(f"{at},{name}")

    return "\n".join(lines)


def parse_stamp_benefits_text(text):
    stamp_benefits = []

    for line in text.splitlines():
        line = line.strip()

        if line == "":
            continue

        # 기본 형식: 5,R석 40% 할인권
        match = re.match(r"([0-9]+)\s*(?:회|개)?\s*[,，]\s*(.+)$", line)

        # 보조 형식: 5회 R석 40% 할인권 / 5개 굿즈
        if match is None:
            match = re.match(r"([0-9]+)\s*(?:회|개)\s+(.+)$", line)

        if match is None:
            continue

        at = int(match.group(1))
        name = match.group(2).strip()

        if at > 0 and name:
            stamp_benefits.append({
                "at": at,
                "name": name
            })

    stamp_benefits.sort(key=lambda item: item["at"])

    return stamp_benefits


def coupons_from_stamp_benefits(stamp_benefits):
    coupons = {}

    for benefit in stamp_benefits:
        name = benefit["name"]
        coupons[name] = 0

    return coupons


def extract_percent_from_text(text):
    match = re.search(r"([0-9]{1,3})\s*%", text)

    if match:
        rate = int(match.group(1))

        if 0 <= rate <= 100:
            return rate

    match = re.search(r"([0-9]{1,3})\s*퍼", text)

    if match:
        rate = int(match.group(1))

        if 0 <= rate <= 100:
            return rate

    return None


def get_coupon_discount_rate(coupon_name):
    if "할인" not in coupon_name and "%" not in coupon_name and "퍼" not in coupon_name:
        return None

    return extract_percent_from_text(coupon_name)


def is_coupon_usable_for_seat(coupon_name, selected_seat):
    seat_names = ["VIP석", "OP석", "R석", "S석", "A석", "B석", "C석", "전석"]

    mentioned_seats = [
        seat for seat in seat_names
        if seat in coupon_name
    ]

    if "전석" in mentioned_seats:
        return True

    if len(mentioned_seats) == 0:
        return True

    return selected_seat in mentioned_seats


def ensure_musical_schema(musical_data):
    default_info = default_musical_info()

    if "discount_rules" not in musical_data:
        musical_data["discount_rules"] = default_info["discount_rules"].copy()

    # 예전 구조 stamp_rules가 있으면 새 구조 stamp_benefits로 변환
    if "stamp_benefits" not in musical_data:
        if "stamp_rules" in musical_data:
            stamp_rules = musical_data["stamp_rules"]

            musical_data["stamp_benefits"] = [
                {
                    "at": stamp_rules.get("discount_coupon_at", 3),
                    "name": "50% 할인 쿠폰"
                },
                {
                    "at": stamp_rules.get("goods_coupon_at", 7),
                    "name": "굿즈/실황 쿠폰"
                }
            ]
        else:
            musical_data["stamp_benefits"] = default_info["stamp_benefits"].copy()

    if "coupons" not in musical_data:
        musical_data["coupons"] = {}

    for benefit in musical_data["stamp_benefits"]:
        name = benefit["name"]

        if name not in musical_data["coupons"]:
            musical_data["coupons"][name] = 0

    if "stamp_boards" not in musical_data:
        musical_data["stamp_boards"] = [0]

    if "records" not in musical_data:
        musical_data["records"] = []

    if "is_hidden" not in musical_data:
        musical_data["is_hidden"] = False


# ========================================================================================
# 5. 도장판 및 쿠폰 처리
# ========================================================================================

def apply_stamp_and_issue_coupons(musical_data, board_index, stamp_count):
    old_count = musical_data["stamp_boards"][board_index]
    new_count = old_count + stamp_count

    musical_data["stamp_boards"][board_index] = new_count

    stamp_benefits = musical_data.get("stamp_benefits", [])
    coupons = musical_data.get("coupons", {})

    for benefit in stamp_benefits:
        at = benefit["at"]
        name = benefit["name"]

        if old_count < at <= new_count:
            coupons[name] = coupons.get(name, 0) + 1

    musical_data["coupons"] = coupons


# ========================================================================================
# 6. 관극 기록 및 직접 수정 처리
# ========================================================================================

def clean_text(value):
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    text = str(value).strip()

    if text.lower() in ["nan", "none", "nat"]:
        return ""

    return text


def safe_int(value, default=0):
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass

    try:
        text = str(value).replace(",", "").strip()

        if text == "":
            return default

        return int(float(text))

    except Exception:
        return default


def normalize_record_date(value):
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    parsed = pd.to_datetime(value, errors="coerce")

    if pd.isna(parsed):
        return clean_text(value)

    return parsed.strftime("%Y-%m-%d")


def date_value_for_editor(value):
    parsed = pd.to_datetime(value, errors="coerce")

    if pd.isna(parsed):
        return None

    return parsed.date()


def stamp_count_from_type(stamp_type):
    stamp_type = clean_text(stamp_type)

    if stamp_type == "기본 적립":
        return 1
    elif stamp_type == "더블 적립":
        return 2
    elif stamp_type == "트리플 적립":
        return 3
    else:
        return 0


def record_sort_key(record):
    date_text = clean_text(record.get("날짜", ""))
    time_text = clean_text(record.get("시간", ""))

    parsed_date = pd.to_datetime(date_text, errors="coerce")

    if pd.isna(parsed_date):
        date_key = "9999-12-31"
    else:
        date_key = parsed_date.strftime("%Y-%m-%d")

    time_match = re.search(r"([0-9]{1,2})\s*:\s*([0-9]{2})", time_text)

    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
        time_key = hour * 60 + minute
    else:
        time_key = 9999

    return (date_key, time_key)


def sort_records_by_datetime(records):
    return sorted(records, key=record_sort_key)


def get_discount_rate_from_name(discount_name, musical_data):
    discount_name = clean_text(discount_name)

    discount_rules = musical_data.get("discount_rules", {})

    if discount_name in discount_rules:
        return safe_int(discount_rules[discount_name])

    if discount_name.startswith("[보유 혜택] "):
        coupon_name = discount_name.replace("[보유 혜택] ", "", 1).strip()
        return get_coupon_discount_rate(coupon_name)

    return get_coupon_discount_rate(discount_name)


def calculate_record_price(row, musical_data, original_record=None):
    if original_record is None:
        original_record = {}

    seat = clean_text(row.get("좌석", ""))
    discount_name = clean_text(row.get("할인", ""))

    seat_prices = musical_data.get("seat_prices", {})

    base_price = safe_int(
        seat_prices.get(
            seat,
            original_record.get("기본 가격", 0)
        )
    )

    manual_final_price = safe_int(
        row.get(
            "결제 금액",
            original_record.get("결제 금액", 0)
        )
    )

    original_booking_fee = safe_int(
        original_record.get("예매수수료", 2000),
        default=2000
    )

    booking_fee = original_booking_fee

    # 현장예매 혜택이면 보통 예매수수료가 없다고 보고 0원 처리
    if "현장예매" in discount_name:
        booking_fee = 0

    discount_rate = get_discount_rate_from_name(discount_name, musical_data)

    # 할인율을 알 수 없는 직접 입력류는 사용자가 적은 결제 금액을 그대로 사용
    if (
        discount_rate is None
        or base_price <= 0
        or discount_name in ["직접 입력", "할인율 직접 입력", "할인 금액 직접 입력"]
    ):
        final_price = manual_final_price
        ticket_price = max(0, final_price - booking_fee)

        return {
            "base_price": base_price,
            "ticket_price": ticket_price,
            "booking_fee": booking_fee,
            "final_price": final_price
        }

    ticket_price = int(base_price * (1 - discount_rate / 100))
    final_price = ticket_price + booking_fee

    return {
        "base_price": base_price,
        "ticket_price": ticket_price,
        "booking_fee": booking_fee,
        "final_price": final_price
    }


def records_to_dataframe(records):
    columns = [
        "날짜",
        "시간",
        "좌석",
        "할인",
        "결제 금액",
        "적립 유형",
        "적립 도장판"
    ]

    sorted_records = sort_records_by_datetime(records)

    rows = []

    for record in sorted_records:
        rows.append({
            "날짜": date_value_for_editor(record.get("날짜", "")),
            "시간": record.get("시간", ""),
            "좌석": record.get("좌석", ""),
            "할인": record.get("할인", ""),
            "결제 금액": record.get("결제 금액", 0),
            "적립 유형": record.get("적립 유형", ""),
            "적립 도장판": safe_int(record.get("적립 도장판", 1), default=1)
        })

    return pd.DataFrame(rows, columns=columns)


def make_record_preview_dataframe(df, musical_data):
    preview_rows = []

    original_records = sort_records_by_datetime(
        musical_data.get("records", [])
    )

    for idx, row in df.iterrows():
        original_record = {}

        if idx < len(original_records):
            original_record = original_records[idx]

        price_info = calculate_record_price(
            row,
            musical_data,
            original_record
        )

        stamp_type = clean_text(row.get("적립 유형", ""))
        stamp_count = stamp_count_from_type(stamp_type)

        preview_rows.append({
            "날짜": normalize_record_date(row.get("날짜", "")),
            "시간": clean_text(row.get("시간", "")),
            "좌석": clean_text(row.get("좌석", "")),
            "할인": clean_text(row.get("할인", "")),
            "자동 계산 결제 금액": price_info["final_price"],
            "적립 유형": stamp_type,
            "자동 적립 도장 수": stamp_count,
            "적립 도장판": safe_int(row.get("적립 도장판", 1), default=1)
        })

    return pd.DataFrame(preview_rows)


def records_from_dataframe(df, musical_data):
    records = []

    original_records = sort_records_by_datetime(
        musical_data.get("records", [])
    )

    for idx, row in df.iterrows():
        original_record = {}

        if idx < len(original_records):
            original_record = original_records[idx]

        watch_date = normalize_record_date(row.get("날짜", ""))
        watch_time = clean_text(row.get("시간", ""))
        seat = clean_text(row.get("좌석", ""))
        discount = clean_text(row.get("할인", ""))
        stamp_type = clean_text(row.get("적립 유형", ""))

        stamp_board = safe_int(row.get("적립 도장판", 1), default=1)

        if stamp_board <= 0:
            stamp_board = 1

        stamp_count = stamp_count_from_type(stamp_type)

        price_info = calculate_record_price(
            row,
            musical_data,
            original_record
        )

        if (
            watch_date == ""
            and watch_time == ""
            and seat == ""
            and discount == ""
            and price_info["final_price"] == 0
            and stamp_count == 0
        ):
            continue

        records.append({
            "날짜": watch_date,
            "시간": watch_time,
            "좌석": seat,
            "기본 가격": price_info["base_price"],
            "할인": discount,
            "티켓 가격": price_info["ticket_price"],
            "예매수수료": price_info["booking_fee"],
            "결제 금액": price_info["final_price"],
            "적립 유형": stamp_type,
            "적립 도장 수": stamp_count,
            "적립 도장판": stamp_board
        })

    return sort_records_by_datetime(records)


def stamp_boards_to_dataframe(stamp_boards):
    rows = []

    for i, stamp_count in enumerate(stamp_boards):
        rows.append({
            "도장판": f"{i + 1}번 도장판",
            "도장 수": int(stamp_count)
        })

    return pd.DataFrame(rows)


def stamp_boards_from_dataframe(df):
    stamp_boards = []

    for _, row in df.iterrows():
        stamp_count = safe_int(row.get("도장 수", 0))

        if stamp_count < 0:
            stamp_count = 0

        stamp_boards.append(stamp_count)

    if len(stamp_boards) == 0:
        stamp_boards = [0]

    return stamp_boards


def recalculate_stamp_boards_and_coupons_from_records(musical_data):
    """
    관극 기록의 '적립 도장 수', '적립 도장판'을 기준으로
    도장판 현황과 보유 혜택을 다시 계산합니다.
    """

    records = musical_data.get("records", [])
    stamp_benefits = musical_data.get("stamp_benefits", [])

    max_board_number = 1

    for record in records:
        board_number = safe_int(record.get("적립 도장판", 1), default=1)

        if board_number > max_board_number:
            max_board_number = board_number

    new_stamp_boards = [0 for _ in range(max_board_number)]

    for record in records:
        board_number = safe_int(record.get("적립 도장판", 1), default=1)
        stamp_count = safe_int(record.get("적립 도장 수", 0), default=0)

        if board_number <= 0:
            board_number = 1

        while board_number > len(new_stamp_boards):
            new_stamp_boards.append(0)

        if stamp_count > 0:
            new_stamp_boards[board_number - 1] += stamp_count

    new_coupons = {}

    for benefit in stamp_benefits:
        benefit_name = benefit.get("name", "")
        benefit_at = safe_int(benefit.get("at", 0), default=0)

        if not benefit_name or benefit_at <= 0:
            continue

        new_coupons[benefit_name] = 0

        for board_stamp_count in new_stamp_boards:
            if board_stamp_count >= benefit_at:
                new_coupons[benefit_name] += 1

    # 관극 기록에서 이미 사용한 보유 혜택은 차감
    for record in records:
        discount_name = clean_text(record.get("할인", ""))

        used_coupon_name = None

        if discount_name.startswith("[보유 혜택] "):
            used_coupon_name = discount_name.replace("[보유 혜택] ", "", 1).strip()

        elif discount_name in new_coupons:
            used_coupon_name = discount_name

        if used_coupon_name is not None and used_coupon_name in new_coupons:
            new_coupons[used_coupon_name] = max(0, new_coupons[used_coupon_name] - 1)

    musical_data["stamp_boards"] = new_stamp_boards
    musical_data["coupons"] = new_coupons


def stamp_benefits_to_dataframe(stamp_benefits):
    rows = []

    for benefit in stamp_benefits:
        rows.append({
            "도장 수": int(benefit.get("at", 1)),
            "혜택명": benefit.get("name", "")
        })

    return pd.DataFrame(rows)


def stamp_benefits_from_dataframe(df):
    stamp_benefits = []

    for _, row in df.iterrows():
        at = safe_int(row.get("도장 수", 0))
        name = clean_text(row.get("혜택명", ""))

        if at > 0 and name:
            stamp_benefits.append({
                "at": at,
                "name": name
            })

    stamp_benefits.sort(key=lambda item: item["at"])

    return stamp_benefits


def coupons_to_dataframe(coupons):
    rows = []

    for name, count in coupons.items():
        rows.append({
            "혜택명": name,
            "보유 개수": int(count)
        })

    return pd.DataFrame(rows)


def coupons_from_dataframe(df):
    coupons = {}

    for _, row in df.iterrows():
        name = clean_text(row.get("혜택명", ""))
        count = safe_int(row.get("보유 개수", 0))

        if name:
            if count < 0:
                count = 0

            coupons[name] = count

    return coupons


# ========================================================================================
# 7. session_state 초기화
# ========================================================================================


if "price_cache" not in st.session_state:
    st.session_state.price_cache = {}

if "musicals" not in st.session_state:
    st.session_state.musicals = {}

if "temp_musical_info" not in st.session_state:
    st.session_state.temp_musical_info = default_musical_info()

if "stamp_benefits" not in st.session_state.temp_musical_info:
    st.session_state.temp_musical_info["stamp_benefits"] = default_musical_info()["stamp_benefits"]

if "seat_price_text" not in st.session_state:
    st.session_state.seat_price_text = seat_prices_to_text(
        st.session_state.temp_musical_info["seat_prices"]
    )

if "discount_text" not in st.session_state or st.session_state.discount_text.strip() == "":
    st.session_state.discount_text = DEFAULT_DISCOUNT_TEXT

# 새 작품 등록 화면: 기본 할인율 입력값
if "early_discount_rate" not in st.session_state:
    st.session_state.early_discount_rate = 20

if "revisit_discount_rate" not in st.session_state:
    st.session_state.revisit_discount_rate = 30


# 새 작품 등록 화면: 도장판 혜택 입력 행
if "stamp_benefit_count" not in st.session_state:
    st.session_state.stamp_benefit_count = 2

if "stamp_benefit_at_0" not in st.session_state:
    st.session_state.stamp_benefit_at_0 = 3

if "stamp_benefit_name_0" not in st.session_state:
    st.session_state.stamp_benefit_name_0 = "50% 할인 쿠폰"

if "stamp_benefit_at_1" not in st.session_state:
    st.session_state.stamp_benefit_at_1 = 7

if "stamp_benefit_name_1" not in st.session_state:
    st.session_state.stamp_benefit_name_1 = "굿즈/실황 쿠폰"

if "stamp_benefits_text" not in st.session_state:
    st.session_state.stamp_benefits_text = stamp_benefits_to_text(
        st.session_state.temp_musical_info["stamp_benefits"]
    )


# ========================================================================================
# 8. 사이드바 메뉴
# ========================================================================================


st.sidebar.title("🎭 관극 기록")

show_hidden_musicals = st.sidebar.checkbox(
    "숨긴 작품 보기",
    value=False
)

visible_musicals_names = []
hidden_musicals_names = []

for musical_title, data in st.session_state.musicals.items():
    ensure_musical_schema(data)

    if data.get("is_hidden", False):
        hidden_musicals_names.append(musical_title)
    else:
        visible_musicals_names.append(musical_title)

if show_hidden_musicals:
    musicals_names = hidden_musicals_names
    st.sidebar.caption(f"숨긴 작품 {len(hidden_musicals_names)}개를 보고 있습니다.")
else:
    musicals_names = visible_musicals_names

menu = st.sidebar.radio("메뉴", ["캘린더", "새 작품 등록"] + musicals_names)


# ========================================================================================
# 9. 메뉴별 화면 구성
# ========================================================================================


# (1) 캘린더 화면
if menu == "캘린더":
    st.title("관극 캘린더")

    today = date.today()

    if "calendar_year" not in st.session_state:
        st.session_state.calendar_year = today.year

    if "calendar_month" not in st.session_state:
        st.session_state.calendar_month = today.month

    col1, col2, col3, col4, _ = st.columns([1.2, 1.2, 1.7, 1.4, 4])

    with col1:
        if st.button("◀ 이전", use_container_width=True):
            if st.session_state.calendar_month == 1:
                st.session_state.calendar_month = 12
                st.session_state.calendar_year -= 1
            else:
                st.session_state.calendar_month -= 1

    with col2:
        if st.button("다음 ▶", use_container_width=True):
            if st.session_state.calendar_month == 12:
                st.session_state.calendar_month = 1
                st.session_state.calendar_year += 1
            else:
                st.session_state.calendar_month += 1

    with col3:
        year_options = list(range(st.session_state.calendar_year - 5, st.session_state.calendar_year + 6))

        st.selectbox(
            "연도",
            year_options,
            format_func=lambda x: f"{x}년",
            key="calendar_year",
            label_visibility="collapsed"
        )

    with col4:
        st.selectbox(
            "월",
            list(range(1, 13)),
            format_func=lambda x: f"{x}월",
            key="calendar_month",
            label_visibility="collapsed"
        )

    year = int(st.session_state.calendar_year)
    month = int(st.session_state.calendar_month)

    cal = calendar.Calendar(firstweekday=6)
    month_days = cal.monthdatescalendar(year, month)

    all_records = []

    for musical_title, data in st.session_state.musicals.items():
        ensure_musical_schema(data)

        for record in data["records"]:
            new_record = record.copy()
            new_record["작품명"] = musical_title
            all_records.append(new_record)

    records_by_date = {}

    for record in all_records:
        record_date = record["날짜"]

        if record_date not in records_by_date:
            records_by_date[record_date] = []

        records_by_date[record_date].append(record)

    st.markdown(
        """
        <style>
        .calendar-table {
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
            font-size: 18px;
        }

        .calendar-table th {
            border: 1px solid #e6e6e6;
            padding: 10px;
            text-align: left;
            color: #777;
            background-color: #fafafa;
        }

        .calendar-table td {
            border: 1px solid #e6e6e6;
            height: 85px;
            vertical-align: top;
            padding: 10px;
            position: relative;
            background-color: white;
        }

        .calendar-day {
            font-weight: 600;
            color: #333;
        }

        .calendar-dot {
            margin-top: 8px;
            display: inline-block;
            font-size: 14px;
            color: #ff6b6b;
        }

        .tooltip-box {
            visibility: hidden;
            opacity: 0;
            position: absolute;
            top: 36px;
            left: 10px;
            z-index: 10;
            width: 240px;
            background-color: #333;
            color: white;
            padding: 10px 12px;
            border-radius: 8px;
            font-size: 14px;
            line-height: 1.5;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
            transition: opacity 0.2s;
        }

        .calendar-cell:hover .tooltip-box {
            visibility: visible;
            opacity: 1;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    weekdays = ["일", "월", "화", "수", "목", "금", "토"]

    calendar_html = "<table class='calendar-table'>"

    calendar_html += "<tr>"
    for weekday in weekdays:
        calendar_html += f"<th>{weekday}</th>"
    calendar_html += "</tr>"

    for week in month_days:
        calendar_html += "<tr>"

        for day in week:
            if day.month != month:
                calendar_html += "<td></td>"
            else:
                day_str = str(day)

                calendar_html += "<td class='calendar-cell'>"
                calendar_html += f"<div class='calendar-day'>{day.day}</div>"

                if day_str in records_by_date:
                    tooltip_lines = []

                    for record in records_by_date[day_str]:
                        musical_name = html.escape(record["작품명"])
                        price = record["결제 금액"]
                        watch_time = html.escape(record.get("시간", ""))

                        tooltip_lines.append(
                            f"{musical_name} / {watch_time} / {price:,}원"
                        )

                    tooltip_text = "<br>".join(tooltip_lines)

                    calendar_html += "<div class='calendar-dot'>● 🎭</div>"
                    calendar_html += f"<div class='tooltip-box'>{tooltip_text}</div>"

                calendar_html += "</td>"

        calendar_html += "</tr>"

    calendar_html += "</table>"

    st.markdown(calendar_html, unsafe_allow_html=True)


# (2) 새 작품 등록 화면

elif menu == "새 작품 등록":
    st.title("새 작품 등록")

    st.info("NOL 티켓에 등록된 공연은 작품명으로 검색해 좌석 가격을 자동으로 불러올 수 있습니다.")

    title = st.text_input(
        "작품명",
        placeholder="작품명을 정확하게 입력해주세요."
    )

    if st.button("NOL 티켓에서 좌석 가격 불러오기"):
        if title.strip() == "":
            st.warning("작품명을 입력해주세요.")

        else:
            search_title = title.strip()

            if search_title in st.session_state.price_cache:
                result = st.session_state.price_cache[search_title]

            else:
                with st.spinner("NOL 티켓에서 좌석 가격을 불러오는 중입니다..."):
                    result = fetch_musical_info_from_nol_search(search_title)

                if result.get("seat_prices"):
                    st.session_state.price_cache[search_title] = result

            if result.get("seat_prices"):
                seat_prices = result["seat_prices"]
                st.session_state.temp_musical_info["seat_prices"] = seat_prices

                st.session_state.seat_price_text = seat_prices_to_text(
                    seat_prices
                )

                st.success("NOL 티켓에서 좌석 가격 정보를 불러왔습니다.")

            else:
                st.warning("좌석 가격을 자동으로 찾지 못했습니다. 아래에 직접 입력해주세요.")

                if result.get("error"):
                    st.caption(f"오류 정보: {result['error']}")

            if result.get("detail_url"):
                st.caption(f"불러온 페이지: {result['detail_url']}")

    st.write("### 좌석별 가격 입력")

    st.caption(
        """좌석명과 가격을 쉼표로 구분해서 한 줄에 하나씩 입력해주세요.
        NOL 티켓에서 가격을 불러온 경우에도 여기서 직접 수정할 수 있습니다."""
    )

    st.text_area(
        "좌석별 가격",
        help="형식: 좌석명,가격 / 예: R석,70000",
        height=120,
        key="seat_price_text"
    )

    st.write("### 기본 할인율 입력")

    st.caption(
        """자주 쓰이는 할인만 간단히 입력합니다.
        다른 할인은 관극 등록 화면에서 직접 입력할 수 있습니다."""
    )

    discount_col1, discount_col2 = st.columns(2)

    with discount_col1:
        st.number_input(
            "조기예매 할인 (%)",
            min_value=0,
            max_value=100,
            step=5,
            key="early_discount_rate"
        )

    with discount_col2:
        st.number_input(
            "재관람 할인 (%)",
            min_value=0,
            max_value=100,
            step=5,
            key="revisit_discount_rate"
        )

    st.write("### 도장판 혜택 입력")

    st.caption(
        """도장을 몇 개 모았을 때 어떤 혜택이 발급되는지 입력해주세요. 같은 도장 개수에 여러 혜택이 있으면 혜택을 여러 줄로 추가하면 됩니다.
        혜택명에 40%, 50%처럼 할인율이 들어 있으면 보유 시 관극 등록 화면의 적용 할인 종류에서 선택할 수 있습니다."""
    )

    add_col, remove_col, _ = st.columns([1.2, 1.2, 4])

    with add_col:
        if st.button("+ 혜택 추가"):
            idx = st.session_state.stamp_benefit_count

            st.session_state[f"stamp_benefit_at_{idx}"] = 1
            st.session_state[f"stamp_benefit_name_{idx}"] = ""

            st.session_state.stamp_benefit_count += 1
            st.rerun()

    with remove_col:
        if st.button("- 마지막 혜택 삭제"):
            if st.session_state.stamp_benefit_count > 1:
                st.session_state.stamp_benefit_count -= 1
                st.rerun()

    for i in range(st.session_state.stamp_benefit_count):
        if f"stamp_benefit_at_{i}" not in st.session_state:
            st.session_state[f"stamp_benefit_at_{i}"] = 1

        if f"stamp_benefit_name_{i}" not in st.session_state:
            st.session_state[f"stamp_benefit_name_{i}"] = ""

        benefit_col1, benefit_col2 = st.columns([1, 4])

        with benefit_col1:
            st.number_input(
                f"{i + 1}번 혜택 도장 수",
                min_value=1,
                step=1,
                key=f"stamp_benefit_at_{i}"
            )

        with benefit_col2:
            st.text_input(
                f"{i + 1}번 혜택명",
                placeholder="예: 50% 할인권 / 실황 OST 교환권",
                key=f"stamp_benefit_name_{i}"
            )

    if st.button("등록"):
        if title.strip() == "":
            st.warning("작품명을 입력해주세요.")

        elif title in st.session_state.musicals:
            st.warning("이미 등록된 작품입니다.")

        else:
            seat_prices = parse_seat_prices_text(st.session_state.seat_price_text)

            discount_rules = {
                "할인 없음": 0,
                "조기예매 할인": int(st.session_state.early_discount_rate),
                "재관람 할인": int(st.session_state.revisit_discount_rate)
            }

            stamp_benefits = []

            for i in range(st.session_state.stamp_benefit_count):
                at = int(st.session_state.get(f"stamp_benefit_at_{i}", 1))
                name = st.session_state.get(f"stamp_benefit_name_{i}", "").strip()

                if name:
                    stamp_benefits.append({
                        "at": at,
                        "name": name
                    })

            stamp_benefits.sort(key=lambda item: item["at"])

            if len(seat_prices) == 0:
                st.warning("좌석 가격을 최소 1개 이상 입력해주세요.")

            elif len(stamp_benefits) == 0:
                st.warning("도장판 혜택을 최소 1개 이상 입력해주세요.")

            else:
                st.session_state.musicals[title] = {
                    "seat_prices": seat_prices,
                    "discount_rules": discount_rules,
                    "stamp_benefits": stamp_benefits,
                    "coupons": coupons_from_stamp_benefits(stamp_benefits),
                    "stamp_boards": [0],
                    "records": []
                }

                st.success(f"{title} 등록 완료!")
                st.rerun()


# (3) 작품별 상세 화면

else:
    selected_musical = menu
    musical_data = st.session_state.musicals[selected_musical]

    ensure_musical_schema(musical_data)

    st.title(selected_musical)

    if musical_data.get("is_hidden", False):
        st.warning("이 작품은 현재 숨긴 작품입니다.")

        if st.button("이 작품 다시 보이기"):
            musical_data["is_hidden"] = False
            st.success("작품을 다시 보이도록 변경했습니다.")
            st.rerun()

    else:
        if st.button("이 작품 숨기기"):
            musical_data["is_hidden"] = True
            st.success("작품을 숨겼습니다. 사이드바의 '숨긴 작품 보기'에서 다시 확인할 수 있습니다.")
            st.rerun()

    musical_data["records"] = sort_records_by_datetime(musical_data["records"])

    records = musical_data["records"]
    count = len(records)
    total_price = sum(record["결제 금액"] for record in records)

    st.info(f"지금까지 총 {count}회 관극 · 총 지출 금액 {total_price:,}원")

    coupons = musical_data["coupons"]

    if len(coupons) == 0:
        st.write("보유 혜택: 없음")
    else:
        coupon_text = " / ".join(
            f"{name} {count}개"
            for name, count in coupons.items()
        )
        st.write(f"보유 혜택: {coupon_text}")


    # =====================================================================================
    # 도장판 현황 직접 수정

    with st.expander("도장판 현황과 보유 혜택 직접 수정"):
        st.caption(
            "실수로 잘못 적립했거나, 도장만 받았거나, 도장판 양도·교환을 한 경우 여기서 직접 수정할 수 있습니다."
        )

        st.write("#### 도장판 현황")

        stamp_board_df = stamp_boards_to_dataframe(musical_data["stamp_boards"])

        edited_stamp_board_df = st.data_editor(
            stamp_board_df,
            num_rows="dynamic",
            use_container_width=True,
            key=f"stamp_board_editor_{selected_musical}",
            column_config={
                "도장판": st.column_config.TextColumn(
                    "도장판",
                    disabled=True
                ),
                "도장 수": st.column_config.NumberColumn(
                    "도장 수",
                    min_value=0,
                    step=1
                )
            }
        )

        st.write("#### 도장판 혜택 기준")

        stamp_benefit_df = stamp_benefits_to_dataframe(musical_data["stamp_benefits"])

        edited_stamp_benefit_df = st.data_editor(
            stamp_benefit_df,
            num_rows="dynamic",
            use_container_width=True,
            key=f"stamp_benefit_rule_editor_{selected_musical}",
            column_config={
                "도장 수": st.column_config.NumberColumn(
                    "도장 수",
                    min_value=1,
                    step=1
                ),
                "혜택명": st.column_config.TextColumn(
                    "혜택명"
                )
            }
        )

        st.write("#### 보유 혜택 수량")

        coupon_df = coupons_to_dataframe(musical_data["coupons"])

        edited_coupon_df = st.data_editor(
            coupon_df,
            num_rows="dynamic",
            use_container_width=True,
            key=f"coupon_editor_{selected_musical}",
            column_config={
                "혜택명": st.column_config.TextColumn(
                    "혜택명"
                ),
                "보유 개수": st.column_config.NumberColumn(
                    "보유 개수",
                    min_value=0,
                    step=1
                )
            }
        )

        if st.button("도장판/혜택 수정 저장", key=f"save_stamp_status_{selected_musical}"):
            new_stamp_boards = stamp_boards_from_dataframe(edited_stamp_board_df)
            new_stamp_benefits = stamp_benefits_from_dataframe(edited_stamp_benefit_df)
            new_coupons = coupons_from_dataframe(edited_coupon_df)

            if len(new_stamp_benefits) == 0:
                st.warning("도장판 혜택 기준을 최소 1개 이상 입력해주세요.")

            else:
                for benefit in new_stamp_benefits:
                    benefit_name = benefit["name"]

                    if benefit_name not in new_coupons:
                        new_coupons[benefit_name] = musical_data["coupons"].get(benefit_name, 0)

                musical_data["stamp_boards"] = new_stamp_boards
                musical_data["stamp_benefits"] = new_stamp_benefits
                musical_data["coupons"] = new_coupons

                st.success("도장판 현황과 보유 혜택을 수정했습니다.")
                st.rerun()


    # =====================================================================================
    # 관극 기록 직접 수정

    with st.expander("관극 기록 직접 수정"):
        st.caption(
            "잘못 등록한 관극 기록을 수정할 수 있습니다. "
            "저장하면 날짜가 이른 기록이 위로 오고, 같은 날짜에서는 시간이 이른 기록이 위로 오도록 자동 정렬됩니다. "
            "할인 선택을 바꾸면 아래 미리보기에서 결제 금액이 자동 계산됩니다."
        )

        record_df = records_to_dataframe(musical_data["records"])

        common_time_options = [
            "14:00", "14:30", "15:00", "16:00",
            "18:00", "18:30", "19:00", "19:30", "20:00"
        ]

        existing_time_options = [
            clean_text(record.get("시간", ""))
            for record in musical_data["records"]
            if clean_text(record.get("시간", "")) != ""
        ]

        time_options_for_editor = list(dict.fromkeys(common_time_options + existing_time_options))

        seat_options_for_editor = list(
            dict.fromkeys(
                list(musical_data["seat_prices"].keys())
                + [
                    clean_text(record.get("좌석", ""))
                    for record in musical_data["records"]
                    if clean_text(record.get("좌석", "")) != ""
                ]
            )
        )

        coupon_discount_options = []

        for coupon_name, coupon_count in musical_data["coupons"].items():
            if get_coupon_discount_rate(coupon_name) is not None:
                coupon_discount_options.append(f"[보유 혜택] {coupon_name}")

        existing_discount_options = [
            clean_text(record.get("할인", ""))
            for record in musical_data["records"]
            if clean_text(record.get("할인", "")) != ""
        ]

        discount_options_for_editor = list(
            dict.fromkeys(
                list(musical_data["discount_rules"].keys())
                + coupon_discount_options
                + ["할인율 직접 입력", "할인 금액 직접 입력", "직접 입력"]
                + existing_discount_options
            )
        )

        existing_stamp_type_options = [
            clean_text(record.get("적립 유형", ""))
            for record in musical_data["records"]
            if clean_text(record.get("적립 유형", "")) != ""
        ]

        stamp_type_options_for_editor = list(
            dict.fromkeys(
                ["기본 적립", "더블 적립", "트리플 적립", "직접 입력"]
                + existing_stamp_type_options
            )
        )

        existing_board_numbers = [
            safe_int(record.get("적립 도장판", 1), default=1)
            for record in musical_data["records"]
        ]

        max_existing_board = max(
            existing_board_numbers + [len(musical_data["stamp_boards"]), 1]
        )

        board_options_for_editor = list(range(1, max_existing_board + 2))

        edited_record_df = st.data_editor(
            record_df,
            num_rows="dynamic",
            use_container_width=True,
            key=f"record_editor_{selected_musical}",
            column_config={
                "날짜": st.column_config.DateColumn(
                    "날짜",
                    format="YYYY-MM-DD",
                    help="달력에서 날짜를 선택할 수 있습니다."
                ),
                "시간": st.column_config.SelectboxColumn(
                    "시간",
                    options=time_options_for_editor
                ),
                "좌석": st.column_config.SelectboxColumn(
                    "좌석",
                    options=seat_options_for_editor
                ),
                "할인": st.column_config.SelectboxColumn(
                    "할인",
                    options=discount_options_for_editor
                ),
                "결제 금액": st.column_config.NumberColumn(
                    "결제 금액",
                    min_value=0,
                    step=1000,
                    help="할인율을 계산할 수 있는 할인은 저장 시 자동 계산됩니다. 직접 입력류 할인은 이 값을 그대로 사용합니다."
                ),
                "적립 유형": st.column_config.SelectboxColumn(
                    "적립 유형",
                    options=stamp_type_options_for_editor
                ),
                "적립 도장판": st.column_config.SelectboxColumn(
                    "적립 도장판",
                    options=board_options_for_editor
                )
            }
        )

        preview_record_df = make_record_preview_dataframe(
            edited_record_df,
            musical_data
        )

        st.write("#### 자동 계산 미리보기")
        st.caption(
            "할인 선택을 바꾸면 아래 미리보기의 결제 금액이 자동으로 계산됩니다. "
            "저장 시 이 미리보기의 결제 금액이 실제 관극 기록에 반영됩니다."
        )

        st.dataframe(
            preview_record_df,
            use_container_width=True,
            hide_index=True
        )

        if st.button("관극 기록 수정 저장", key=f"save_records_{selected_musical}"):
            musical_data["records"] = records_from_dataframe(
                edited_record_df,
                musical_data
            )

            recalculate_stamp_boards_and_coupons_from_records(musical_data)

            st.success("관극 기록, 총 지출 금액, 도장판 현황, 보유 혜택을 수정했습니다.")
            st.rerun()

    st.write("### 관극 정보 등록")

    watch_date = st.date_input("관극 날짜", value=date.today())

    time_options = [
        "14:00", "14:30", "15:00", "16:00",
        "18:00", "18:30", "19:00", "19:30", "20:00",
        "직접 입력"
    ]

    selected_time = st.selectbox("관극 시간", time_options)

    if selected_time == "직접 입력":
        watch_time = st.text_input("직접 입력", placeholder="예: 20:00")
    else:
        watch_time = selected_time

    seat_prices = musical_data["seat_prices"]

    seat = st.selectbox("좌석", list(seat_prices.keys()))

    price_mode = st.radio(
        "결제 금액 입력 방식",
        ["좌석 가격 기반 계산", "직접 입력"],
        horizontal=True
    )

    base_price = seat_prices[seat]

    selected_coupon_name = None

    if price_mode == "좌석 가격 기반 계산":
        st.markdown(f"선택한 좌석의 기본 가격: **{base_price:,}원**")

        discount_rules = musical_data["discount_rules"]

        available_coupon_discount_options = []

        for coupon_name, coupon_count in coupons.items():
            discount_rate = get_coupon_discount_rate(coupon_name)

            if coupon_count > 0 and discount_rate is not None:
                available_coupon_discount_options.append(f"[보유 혜택] {coupon_name}")

        discount_options = (
            list(discount_rules.keys())
            + available_coupon_discount_options
            + ["할인율 직접 입력", "할인 금액 직접 입력"]
        )

        discount_type = st.selectbox("적용 할인 종류", discount_options)

        if discount_type in discount_rules:
            discount_rate = discount_rules[discount_type]
            ticket_price = int(base_price * (1 - discount_rate / 100))

        elif discount_type.startswith("[보유 혜택] "):
            selected_coupon_name = discount_type.replace("[보유 혜택] ", "", 1)
            discount_rate = get_coupon_discount_rate(selected_coupon_name)

            if discount_rate is None:
                discount_rate = 0

            ticket_price = int(base_price * (1 - discount_rate / 100))

            if not is_coupon_usable_for_seat(selected_coupon_name, seat):
                st.warning(f"선택한 혜택은 {seat}에 적용하기 어려울 수 있습니다.")

        elif discount_type == "할인율 직접 입력":
            discount_rate = st.number_input(
                "할인율 입력 (%)",
                min_value=0,
                max_value=100,
                step=1
            )
            ticket_price = int(base_price * (1 - discount_rate / 100))

        elif discount_type == "할인 금액 직접 입력":
            discount_amount = st.number_input(
                "할인 금액 입력",
                min_value=0,
                step=1000
            )
            ticket_price = max(0, base_price - discount_amount)

    else:
        discount_type = "직접 입력"
        ticket_price = st.number_input(
            "티켓 가격 입력 (예매수수료 제외)",
            min_value=0,
            step=1000
        )

    booking_fee_yes = st.checkbox("예매 수수료 포함", value=True)

    booking_fee = 2000 if booking_fee_yes else 0
    final_price = ticket_price + booking_fee

    st.write("### 도장판 적립")

    stamp_type = st.radio(
        "적립 유형",
        ["기본 적립", "더블 적립", "트리플 적립"],
        horizontal=True
    )

    if stamp_type == "기본 적립":
        stamp_count = 1
    elif stamp_type == "더블 적립":
        stamp_count = 2
    else:
        stamp_count = 3

    stamp_boards = musical_data["stamp_boards"]

    selected_board_key = f"selected_board_{selected_musical}_radio"

    # 예전 session_state 값이 문자열로 남아 있을 수 있어서,
    # radio 위젯이 만들어지기 전에 숫자로 정리
    if selected_board_key not in st.session_state:
        st.session_state[selected_board_key] = 0

    try:
        st.session_state[selected_board_key] = int(st.session_state[selected_board_key])
    except:
        st.session_state[selected_board_key] = 0

    if st.session_state[selected_board_key] < 0:
        st.session_state[selected_board_key] = 0

    if st.session_state[selected_board_key] >= len(stamp_boards):
        st.session_state[selected_board_key] = 0

    selected_board_index = st.radio(
        "적립할 도장판을 선택해주세요",
        options=list(range(len(stamp_boards))),
        format_func=lambda i: f"{i + 1}번 도장판 ({stamp_boards[i]}개)",
        horizontal=True,
        key=selected_board_key
    )

    try:
        selected_board_index = int(selected_board_index)
    except:
        selected_board_index = 0

    if st.button("+ 새 도장판 추가"):
        stamp_boards.append(0)
        st.rerun()

    stamp_benefits = musical_data["stamp_benefits"]

    benefit_lines = []

    for benefit in stamp_benefits:
        benefit_lines.append(f'{benefit["at"]}개: {benefit["name"]}')

    benefit_text = " / ".join(benefit_lines)

    st.markdown(
        f"""
        이번 관극으로 **{stamp_count}개** 도장 적립
        도장판 혜택 (**{benefit_text}**)
        """
    )

    st.write("### 결제 금액 정리")

    st.markdown(
        f"""
        **티켓 가격:** {ticket_price:,}원
        **예매수수료:** {booking_fee:,}원
        **최종 결제 금액:** {final_price:,}원
        """
    )

    if st.button("관극 기록 추가"):
        if watch_time.strip() == "":
            st.warning("관극 시간을 입력해주세요.")

        elif selected_coupon_name is not None and coupons.get(selected_coupon_name, 0) <= 0:
            st.warning("사용 가능한 해당 혜택이 없습니다.")

        elif selected_coupon_name is not None and not is_coupon_usable_for_seat(selected_coupon_name, seat):
            st.warning(f"선택한 혜택은 {seat}에 사용할 수 없습니다.")

        else:
            selected_board_index = int(selected_board_index)

            if selected_coupon_name is not None:
                coupons[selected_coupon_name] = coupons.get(selected_coupon_name, 0) - 1

            apply_stamp_and_issue_coupons(
                musical_data,
                selected_board_index,
                stamp_count
            )

            new_record = {
                "날짜": str(watch_date),
                "시간": watch_time,
                "좌석": seat,
                "기본 가격": base_price,
                "할인": discount_type,
                "티켓 가격": ticket_price,
                "예매수수료": booking_fee,
                "결제 금액": final_price,
                "적립 유형": stamp_type,
                "적립 도장 수": stamp_count,
                "적립 도장판": selected_board_index + 1
            }

            musical_data["records"].append(new_record)
            musical_data["records"] = sort_records_by_datetime(musical_data["records"])

            st.success("관극 기록이 추가되었습니다.")
            st.rerun()

    musical_data["records"] = sort_records_by_datetime(musical_data["records"])
    records = musical_data["records"]

    st.write("### 관극 기록")

    if len(records) == 0:
        st.info("아직 등록된 관극 기록이 없습니다.")

    else:
        display_records = []

        for record in records:
            display_records.append({
                "날짜": record.get("날짜", ""),
                "시간": record.get("시간", ""),
                "좌석": record.get("좌석", ""),
                "할인": record.get("할인", ""),
                "결제 금액": f"{record.get('결제 금액', 0):,}원",
                "적립 도장 수": f"{record.get('적립 도장 수', 0)}개"
            })

        df = pd.DataFrame(display_records)
        st.table(df.style.hide(axis="index"))

        total_price = sum(record["결제 금액"] for record in records)
        st.write(f"총 지출 금액: {total_price:,}원")
