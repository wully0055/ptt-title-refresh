import requests
import time
from bs4 import BeautifulSoup
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

keyword = "你想爬的ptt文章標題"
save = []

def get(url):
    response = requests.get(url)
    return response

def send_email(msg):
    content = MIMEMultipart()  # 建立MIMEMultipart物件
    content["subject"] = "搜尋到" + str(len(href))+ "篇【 "+keyword+" 】相關標題文章" # 郵件標題
    content["from"] = ""  # 寄件者
    content["to"] = "email1, email2, ..."  # 收件者
    content.attach(MIMEText(msg))  # 郵件內容
    pwd = '' # 你的google應用程式密碼
    with smtplib.SMTP(host="smtp.gmail.com", port="587") as smtp:  # 設定SMTP伺服器
        try:
            smtp.ehlo()  # 驗證SMTP伺服器
            smtp.starttls()  # 建立加密傳輸
            smtp.login("your mail", pwd)  # 登入寄件者gmail
            smtp.send_message(content)  # 寄送郵件
            print("Complete!")
        except Exception as e:
            print("Error message: ", e)    



while (True) :
    chose = []
    response = requests.get("url")    # ptt url
    soup = BeautifulSoup(response.text, "html.parser") # 解析原始碼
    num = soup.find_all("div", class_="nrec") # 抓文章前面的數字
    title = soup.find_all("div", class_="title") # 抓文章標題 
    href =[]

    for list in title:

        if ((list.text.strip()).find(keyword) != -1) :    
            
            if list.text.strip() not in save : #如果save陣列沒有該值
                
                save.append(list.text.strip()) #存進save陣列
                chose.append(list.text.strip()) #把符合的標題存入陣列
                item_href = list.select_one("a").get("href")
                href.append(item_href)

    if chose != []:
        msg =""
        for address in range(len(href)):    
            msg = msg+"【 "+keyword+" 】關鍵字有新文章\n 給你連結，趕快去看\n https://www.ptt.cc/"+href[address]+"\n\n"

        print(msg)
        send_email(msg)

    localtime = time.localtime()
    result = time.strftime("%Y-%m-%d %I:%M:%S %p", localtime)
    print(result)
    print("----------------------------------------")

    time.sleep(900)
