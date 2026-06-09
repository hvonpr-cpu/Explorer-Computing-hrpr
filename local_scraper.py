import json
import re
import time
from pathlib import Path
from urllib.parse import quote

from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoAlertPresentException,
    StaleElementReferenceException
)


OUTPUT_FILE = "scraped_prices.json"


def make_chrome_options(headless=False):
    options = Options()

    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--log-level=3")

    options.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36"
    )

    return options


def extract_seat_prices_from_text(text):
    seat_prices = {}

    pattern = r"(VIP석|OP석|R석|S석|A석|B석|C석|전석)\s*[\n\r\t ]*(?:일반\s*)?[\n\r\t ]*([0-9]{1,3}(?:,[0-9]{3})*)\s*원"
    matches = re.findall(pattern, text)

    for seat, price in matches:
        seat_prices[seat] = int(price.replace(",", ""))

    return seat_prices


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

    return seat_prices


def extract_seat_prices_from_driver(driver):
    seat_names = ["VIP석", "OP석", "R석", "S석", "A석", "B석", "C석", "전석"]

    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(1)

    last_body_text = ""

    for _ in range(18):
        body_text = driver.find_element(By.TAG_NAME, "body").text
        last_body_text = body_text

        if any(seat in body_text for seat in seat_names) and "원" in body_text:
            break

        driver.execute_script("window.scrollBy(0, 700);")
        time.sleep(0.7)

    candidate_texts = []

    for seat in seat_names:
        elems = driver.find_elements(
            By.XPATH,
            f"//*[contains(normalize-space(), '{seat}')]"
        )

        for elem in elems:
            try:
                current = elem

                for _ in range(8):
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
        all_text = last_body_text

    seat_prices = extract_seat_prices_from_text(all_text)

    if len(seat_prices) == 0:
        soup = BeautifulSoup(driver.page_source, "html.parser")
        seat_prices = extract_seat_prices_from_soup(soup)

    if len(seat_prices) == 0:
        seat_prices = extract_seat_prices_from_text(driver.find_element(By.TAG_NAME, "body").text)

    return seat_prices


def search_and_scrape_prices(title):
    driver = webdriver.Chrome(options=make_chrome_options(headless=False))
    wait = WebDriverWait(driver, 20)

    try:
        print(f"\n[검색 시작] {title}")

        # 검색창에 직접 입력하지 않고, 검색 결과 URL로 바로 이동
        search_url = f"https://isearch.interpark.com/result?q={quote(title)}&referrer="
        driver.get(search_url)

        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(3)

        print(f"[검색 결과 페이지] {driver.current_url}")

        first_result = None
        detail_url = ""

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
                    for elem in elems:
                        try:
                            href = elem.get_attribute("href")

                            if href and "/goods/" in href:
                                first_result = elem
                                detail_url = href
                                break

                        except StaleElementReferenceException:
                            continue

                    if detail_url:
                        break

            except TimeoutException:
                pass

        if not detail_url:
            print("[실패] 검색 결과에서 상세 페이지 주소를 찾지 못했습니다.")
            return {}

        print(f"[상세 페이지] {detail_url}")

        # 클릭하지 않고 상세 페이지 URL로 직접 이동
        driver.get(detail_url)

        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(5)

        try:
            alert = driver.switch_to.alert
            alert_text = alert.text
            alert.accept()
            print(f"[alert 발생] {alert_text}")
            time.sleep(1)

            # alert가 떠도 다시 상세 URL로 직접 이동
            driver.get(detail_url)
            wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            time.sleep(5)

        except NoAlertPresentException:
            pass

        if "/goods/" not in driver.current_url:
            print(f"[실패] 상품 상세 페이지가 아닙니다: {driver.current_url}")
            return {}

        seat_prices = extract_seat_prices_from_driver(driver)

        if seat_prices:
            print("[성공]", seat_prices)
        else:
            body_text = driver.find_element(By.TAG_NAME, "body").text
            page_source = driver.page_source

            print("[실패] 좌석 가격을 찾지 못했습니다.")
            print("현재 URL:", driver.current_url)
            print("body 길이:", len(body_text))
            print("body R석:", "R석" in body_text)
            print("body S석:", "S석" in body_text)
            print("body 원:", "원" in body_text)
            print("html R석:", "R석" in page_source)
            print("html S석:", "S석" in page_source)
            print("html 원:", "원" in page_source)

        return seat_prices

    except Exception as e:
        print("[오류]", type(e).__name__, e)
        return {}

    finally:
        driver.quit()


def load_existing_data():
    path = Path(OUTPUT_FILE)

    if not path.exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception:
        return {}


def save_data(data):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n[저장 완료] {OUTPUT_FILE}")


def main():
    data = load_existing_data()

    print("NOL 티켓 좌석 가격 로컬 크롤러")
    print("여러 작품을 입력하려면 쉼표로 구분하세요.")
    print("예: 시데레우스, 종의 기원")

    raw_titles = input("\n작품명 입력: ").strip()

    if raw_titles == "":
        print("작품명이 입력되지 않았습니다.")
        return

    titles = [title.strip() for title in raw_titles.split(",") if title.strip()]

    for title in titles:
        prices = search_and_scrape_prices(title)

        if prices:
            data[title] = prices
            save_data(data)

    print("\n최종 수집 데이터:")
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()