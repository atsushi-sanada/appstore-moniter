# App Store Moniter

## 概要

App Store Connect APIから会社の全アプリを毎日ポーリングし、
予約注文中かつリリース予定日がN日以内のアプリをSlackへ通知します。
リリース延期時に予約注文の予定日変更を忘れるリスクを減らします。

### このツールについて

- 会社コード単位で監視対象を識別します
- App Store Connect APIで参照可能な全アプリを取得します
- 確認したアプリ一覧と予約注文ステータスをActionsログへ出します
- 指定SlackチャンネルへBot Tokenで通知します

---

## クイックスタート

1. `pip install -r requirements.txt`
2. `config/settings.json` の会社コードとSlackチャンネルを確認
3. `python src/appstore_moniter.py --source fixture --dry-run`

---

## セットアップ

- 前提条件: Python 3.10以上
- 必要権限: App Store Connect APIキー、Slack Bot Token

1. `config/settings.json` の `company_code`、`notify_days`、`poll_time` を編集
2. `APPSTORE_ISSUER_ID`、`APPSTORE_KEY_ID`、`APPSTORE_PRIVATE_KEY_PATH` を設定
3. `SLACK_BOT_TOKEN` を設定し、`slack.channel` に通知先を設定
4. Slack Botを通知先チャンネルへ参加させる
5. 毎日1回実行されるジョブへ `python src/appstore_moniter.py --notify slack` を登録

---

## 使い方

1. 検証用データで確認する:
   `python src/appstore_moniter.py --source fixture --dry-run`
2. App Store Connect APIをポーリングする:
   `python src/appstore_moniter.py --notify slack`
3. 常駐モードで `poll_time` に毎日実行する:
   `python src/appstore_moniter.py --daemon --notify slack`
4. 通知対象日数を一時変更する:
   `python src/appstore_moniter.py --notify-days 14 --notify slack`
5. ヘルプを確認する: `python src/appstore_moniter.py --help`

---

## その他

- 運用場所はGitHub EnterpriseのPrivateリポジトリとGitHub Actionsを第一候補にします
- `config/settings.json` は共通設定です。秘密鍵とSlack Tokenは環境変数またはGitHub Secretsで管理してください
- 固定時刻は `.github/workflows/appstore-moniter.yml` のcron、または `--daemon` 常駐で管理できます
- 詳細な設定手順は `docs/setup_guide.md` を参照してください
