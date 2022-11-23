import requests
import time
import requests
from bs4 import BeautifulSoup

gift = "送"
sale = "特價"
line = "ine"
off = "折"
discount = "優惠"
save = []
j = 0
mail = 'willy211468@gmail.com'
while 1==1 :
    chose = []
    response = requests.get("https://www.ptt.cc/bbs/Lifeismoney/index.html")    # 以ptt 省錢版為例
    # html = response.content
    soup = BeautifulSoup(response.text, "html.parser") # 解析原始碼
    num = soup.find_all("div", class_="nrec") # 抓文章前面的數字
    title = soup.find_all("div", class_="title") # 抓文章標題 

    for list in title:

        # print(type(title))
        # print(list.text.strip())
        # print((list.text.strip()).find(gift))  #尋找文章標題有沒有'送'
        if ((list.text.strip()).find(gift) != -1) | ((list.text.strip()).find(sale) != -1) | ((list.text.strip()).find(line) != -1) | ((list.text.strip()).find(off) != -1) | ((list.text.strip()).find(discount) != -1) :
            # print('1')
            # print(list.text.strip() not in chose)
            if list.text.strip() not in save : #如果save陣列沒有該值
                
                save.append(list.text.strip()) #存進save陣列
                chose.append(list.text.strip()) #把符合的標題存入陣列

    j+=1     
    if j != 1  :
        if chose != []:
        # 寄信
            url = 'https://mail.weeshopstyle.com/send_email/update/send.php'
            requests.post(url, data = {'list': "<br><br>".join(chose),'email':mail})



    print(chose)
    print(save)
    # print(j)
    localtime = time.localtime()
    result = time.strftime("%Y-%m-%d %I:%M:%S %p", localtime)
    print(result)

    time.sleep(900)
