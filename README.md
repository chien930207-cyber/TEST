# TEAM / ID - GitHub Pages 上架版

九個聯盟的隊徽猜題遊戲。沿用 v5 的 136 隊題庫，改由 GitHub Actions 下載圖片，再用 GitHub Pages 發布。玩家不需安裝、執行 CMD，或連接第三方圖片代理。

## 這個版本實際包含什麼

- CPBL 6、TPBL 7、PLG 4、MLB 30、NBA 30、NPB 12、KBO 10、TPVL 5、NFL 32，共 136 隊名單與圖源設定。
- 每輪預設隨機 10 題，不重複；也能選 20 題或全部。可選「只抽 Logo + 球衣都齊全」。
- 先只顯示 Logo；點一下揭曉中英文隊名和已取得的球衣。可自行標記答對／答錯計分。
- 匯出本輪動畫 PPT、雙頁 PPT、內嵌圖片的離線 HTML、圖片原檔 ZIP。
- 原圖不縮圖、不放大做假高解析度；優先保留 SVG。題庫會顯示實際像素與低解析度警示。

**請注意：此 ZIP 是網站程式與自動下載流程，不是已下載齊全的圖片包。正式圖片會在你的 GitHub Actions 執行時取得。** 所有成功率、尺寸與缺圖以該次建置報告為準，不保證所有球隊、最新年度或全網最高解析度均可取得。沒有圖片時不用假圖補滿。

## 第一次上架（不用安裝程式）

1. 在 GitHub 建立新儲存庫，例如 `TEAM-ID`。一般免費個人帳號請用 Public；企業帳號的 Pages 與 Actions 需依管理員政策。
2. 解壓縮後，將 `TEAM-ID` 資料夾**內部的檔案與資料夾**上傳到儲存庫根目錄。根目錄必須直接看到 `index.html`、`data`、`scripts`、`tests`、`requirements.txt`。不要只上傳 ZIP，也不要多包一層目錄。
3. **確認 `.github/workflows/deploy.yml` 有上傳。** 點開儲存庫的 `.github` 資料夾檢查。若隱藏資料夾沒有被上傳，使用 Add file > Create new file，檔名輸入 `.github/workflows/deploy.yml`，貼上套件內 `DEPLOY_WORKFLOW.yml` 的全部內容，再 Commit changes。
4. 進入 **Settings > Pages > Build and deployment > Source**，選擇 **GitHub Actions**。不是 Deploy from a branch。
5. 進入 **Actions > Build images and deploy TEAM ID > Run workflow**，選 main（或 master），執行。不需要 API key，不需要把 GitHub token 貼到網頁。
6. 建置成功後，開啟該次 workflow 的 **deploy** 連結，或 Settings > Pages 顯示的網址。一般為 `https://YOUR-USERNAME.github.io/TEAM-ID/`。

自訂的 repo 名稱可以不同，所有本網站路徑都使用相對路徑，不用改程式。

## 圖片實際會放哪裡？

GitHub runner 會下載圖片到建置產物的 `assets/images/`，與網站一起發布到 Pages。玩家的瀏覽器只讀取同一個網站的圖片，不會用瀏覽器拒絕的跨站 fetch 抓球團圖片。

圖片不會自動 commit 回原始碼儲存庫，避免資料夾變得太大。已下載的原圖以 Actions cache 保留供下次建置重用；快取並非永久儲存，可另行下載備份。

在 Actions 該次執行頁面下方，可下載 **team-id-site-and-image-report** 產物，內含已抓到的原圖、網站與 `data/image-report.csv`。亦可在網站直接按「下載所選聯盟原圖 ZIP」。

## 缺圖、正面與畫質政策

- 有 Logo 就可玩，缺球衣不擋匯出。缺 Logo 的球隊不會進入抽題池。不足 10 隊時使用實際題數，不用重複題補滿。
- 如果 **0 隊 Logo** 下載成功，部署會中止，不發布全空白遊戲。以前已發布的網站不會被空網站取代。
- 優先用官方代表性隊徽，不以紀念版、新聞首圖或隨機圖片取代。
- 球衣先挑主場 / Icon / 代表款，正面標記優先，排除明確背面、特寫與尺寸表。MLB 不接受單憑 `pv-1` 編號的主圖，避免把正背合併圖當正面。
- **自動篩圖不等於逐張目視確認。** `frontStatus` 會記錄是正面標記或商品候選圖，未確認的不會謊報為人工檢查完成。活動前請在圖庫檢視。
- 來源圖太小就如實標示，不使用 AI 重畫隊徽，不用小圖放大冒充原圖。
- 尊重來源的 robots.txt、TLS 與存取限制；不登入外站、不繞過驗證碼。網站阻擋時記錄缺圖，不會宣稱全部下載成功。

## 重抓圖片與更換圖源

在 Actions 重新 Run workflow，預設保留已成功下載的圖片，補抓缺圖。勾選 `refresh_images` 才會重試已有圖片的來源；失敗時保留舊原圖。

`data/sources.json` 是建置用圖源目錄。可更換該隊的 `logos`（圖片直接網址）、`jerseyDirect`（正面原圖）或 `jerseyPages`（官方商品頁），commit 後自動重建。只更換該隊圖源不用更新頁面內的常用名單；若要改隊名或新增球隊，須同步更新頁面名單與 PPT 範本。

網頁內「換圖」只存在你當下的瀏覽器，不會上傳或改到其他玩家的圖庫。

## 本機開發（選用）

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p 'test_*.py' -v
python scripts/build_site.py
python scripts/collect_assets.py --output _site
python -m http.server 8080 --directory _site
```

## 已測試與尚未測試

請參閱 `VALIDATION.md`。本次交付未連線到你的 GitHub，並未代你完成實際上架。也未宣稱 272 張正式圖片均已下載。

## 權利與隱私

本專案不隸屬於各聯盟或球團。球隊商標、隊徽、球衣攝影與商品圖的權利歸原權利人。公開上架前請確認圖片使用授權，尤其是商業用途。程式的交付不代表附帶圖片授權。網站無廣告、無追蹤分析、無帳號系統；手動換圖存在本機 IndexedDB。

## 官方部署文件

- https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site
- https://docs.github.com/en/get-started/start-your-journey/deploying-your-website-automatically
- https://github.com/actions/upload-pages-artifact
- https://github.com/actions/deploy-pages

## 內建第三方程式

頁面內保留 JSZip 3.10.1 的原始版權注記（MIT / GPLv3 雙重授權）。使用既有 PptxGenJS 產生的範本進行圖片內嵌與動畫匹配。系統字型不包在交付檔中。
