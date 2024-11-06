import requests
import time
from bs4 import BeautifulSoup
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

# 設定參數
keyword = ""                        # 文章標題關鍵字
save = set()                        # 儲存已經發送過的文章標題
ptt_url = ""                        # PTT URL
sender_email = ""                   # 寄件者 Email
receiver_emails = ["", ""]          # 收件者 Email
app_password = ""                   # Google 應用程式密碼
check_interval = 60                 # 檢查間隔時間 (秒)

def get(url):
    """取得 URL 的回應."""
    try:
        response = requests.get(url)
        response.raise_for_status()  # 若失敗則拋出錯誤
        return response
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from {url}: {e}")
        return None

def send_email(subject, msg):
    """寄送通知信件."""
    content = MIMEMultipart()
    content["subject"] = subject
    content["from"] = sender_email
    content["to"] = ", ".join(receiver_emails)
    content.attach(MIMEText(msg))

    try:
        with smtplib.SMTP(host="smtp.gmail.com", port="587") as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(sender_email, app_password)
            smtp.send_message(content)
            print("Email sent successfully!")
    except smtplib.SMTPException as e:
        print(f"Error sending email: {e}")

def fetch_titles():
    """抓取 PTT 文章標題及連結."""
    response = get(ptt_url)
    if response is None:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    titles = soup.find_all("div", class_="title")
    new_posts = []

    for title in titles:
        title_text = title.text.strip()
        if keyword.lower() in title_text.lower() and title_text.lower() not in save:
            save.add(title_text)
            link = title.select_one("a").get("href")
            full_link = f"https://www.ptt.cc{link}"
            new_posts.append((title_text, full_link))

    return new_posts

def main():
    while True:
        new_posts = fetch_titles()
        if new_posts:
            msg = "\n\n".join([f"【{keyword}】關鍵字新文章：{title}\n連結：{link}" for title, link in new_posts])
            subject = f"搜尋到 {len(new_posts)} 篇【{keyword}】相關標題文章"
            print(msg)
            send_email(subject, msg)

        # 打印時間戳
        print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
        print("----------------------------------------")

        # 等待下次檢查
        time.sleep(check_interval)

if __name__ == "__main__":
    main()