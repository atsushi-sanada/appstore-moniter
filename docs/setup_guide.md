# App Store Moniter セットアップガイド

## 目次

- [1. はじめに](#1-はじめに)
- [2. 事前に用意するもの](#2-事前に用意するもの)
- [3. STEP 1: App Store Connect APIキーを作成する](#3-step-1-app-store-connect-apiキーを作成する)
- [4. STEP 2: Slack APIのBot Tokenを作成する](#4-step-2-slack-apiのbot-tokenを作成する)
- [5. STEP 3: GitHub EnterpriseにSecretsを登録する](#5-step-3-github-enterpriseにsecretsを登録する)
- [6. STEP 4: 通知先と会社コードを設定する](#6-step-4-通知先と会社コードを設定する)
- [7. STEP 5: GitHub Actionsを手動実行する](#7-step-5-github-actionsを手動実行する)
- [8. 日常の使い方](#8-日常の使い方)
- [9. システムの停止と再起動](#9-システムの停止と再起動)
- [10. 困ったときは](#10-困ったときは)
- [11. 用語集](#11-用語集)

## 1. はじめに

このツールは、App Storeで予約注文中の自社アプリを毎日確認し、
リリース予定日が近いアプリをSlackに通知します。
目的は、リリース延期などで予約注文の予定日変更を忘れることを防ぐことです。

システムがやること:

- App Store Connect APIから会社の全アプリを取得します。
- 予約注文中のアプリだけを見つけます。
- リリース予定日がN日以内ならSlackへ通知します。

あなたがやること:

- App Store Connect APIキーを作成します。
- Slack Bot Tokenを作成します。
- GitHub EnterpriseのSecretsに秘密情報を登録します。

## 2. 事前に用意するもの

| 名前 | 説明 | 入手方法 |
| --- | --- | --- |
| App Store Connect権限 | App Store Connect APIキーを作る権限 | Account Holder、Admin、App Managerなどの権限を持つ人に依頼 |
| Slack管理権限 | Slack Appを作る権限 | Slack管理者に依頼 |
| GitHub Enterprise権限 | Secretsを登録しActionsを実行する権限 | リポジトリ管理者に依頼 |
| 通知先チャンネル | 通知を送るSlackチャンネル | 例: `#release-alerts` |

> **重要:** APIキー、秘密鍵、Bot Tokenは秘密情報です。チャットやメールに貼らず、
> GitHub Secretsへ登録してください。

## 3. STEP 1: App Store Connect APIキーを作成する

1. ブラウザで [App Store Connect](https://appstoreconnect.apple.com/) を開きます。
2. **「Users and Access」** を開きます。
3. **「Integrations」** タブを開きます。
4. **「App Store Connect API」** の **「Keys」** を開きます。
5. **「+」** をクリックします。
6. Key Nameに `appstore-moniter` と入力します。
7. Accessはアプリ情報を読める権限を選びます。
8. **「Generate」** をクリックします。
9. 表示された **Issuer ID** と **Key ID** を控えます。
10. `.p8` の秘密鍵ファイルをダウンロードします。

> **確認ポイント:** `Issuer ID`、`Key ID`、`.p8` ファイルの3つが揃えばOKです。

## 4. STEP 2: Slack APIのBot Tokenを作成する

1. ブラウザで [Slack API Apps](https://api.slack.com/apps) を開きます。
2. **「Create New App」** をクリックします。
3. **「From scratch」** を選びます。
4. App Nameに `appstore-moniter` と入力します。
5. 対象Workspaceを選び、**「Create App」** をクリックします。
6. 左メニューの **「OAuth & Permissions」** を開きます。
7. **「Bot Token Scopes」** に `chat:write` を追加します。
8. **「Install to Workspace」** をクリックします。
9. 表示された `xoxb-` で始まる **Bot User OAuth Token** を控えます。
10. 通知先Slackチャンネルで `/invite @appstore-moniter` を実行します。

> **確認ポイント:** `xoxb-` で始まるTokenがあり、Botが通知先チャンネルに参加していればOKです。

## 5. STEP 3: GitHub EnterpriseにSecretsを登録する

1. `https://github.enish.jp/doge/appstore-moniter` を開きます。
2. **「Settings」** を開きます。
3. **「Secrets and variables」** の **「Actions」** を開きます。
4. **「New repository secret」** をクリックします。
5. `APPSTORE_ISSUER_ID` にIssuer IDを登録します。
6. `APPSTORE_KEY_ID` にKey IDを登録します。
7. `APPSTORE_PRIVATE_KEY` に `.p8` ファイルの中身を登録します。
   `-----BEGIN PRIVATE KEY-----` と `-----END PRIVATE KEY-----` がない本文部分だけでも動作します。
8. `SLACK_BOT_TOKEN` にSlackのBot User OAuth Tokenを登録します。

> **確認ポイント:** Actions Secretsに4つの名前が表示されればOKです。

## 6. STEP 4: 通知先と会社コードを設定する

1. リポジトリ内の `config/settings.json` を開きます。
2. `company_code` を通知表示用の任意コードへ変更します。
   App Store Connect上の項目ではないため、会社名やチーム名の短い英数字を指定します。
3. `notify_days` を通知開始日数へ変更します。
4. `slack.channel` を通知先チャンネルへ変更します。
5. 変更をコミットしてGitHub Enterpriseへpushします。

`config/settings.json` には秘密情報を書きません。
秘密情報はGitHub Secrets、またはローカルPCの環境変数に設定します。

設定例:

```json
{
  "company_code": "doge",
  "notify_days": 7,
  "poll_time": "09:00",
  "slack": {
    "bot_token_env": "SLACK_BOT_TOKEN",
    "channel": "#release-alerts"
  }
}
```

> **確認ポイント:** `company_code` と `slack.channel` が実運用の値になっていればOKです。

## 7. STEP 5: GitHub Actionsを手動実行する

1. GitHub Enterpriseのリポジトリを開きます。
2. **「Actions」** タブを開きます。
3. **「App Store Moniter」** を選びます。
4. **「Run workflow」** をクリックします。
5. 実行が終わるまで待ちます。
6. Slackチャンネルに通知が届くか確認します。

> **確認ポイント:** Actionsが緑色の成功表示になればOKです。
> 対象アプリがない日はSlack通知が出ず、ログに確認したアプリ一覧と
> `No apps need notification today.` が表示されます。

## 8. 日常の使い方

通常は何もしなくて問題ありません。
GitHub Actionsが毎日決まった時刻に自動実行します。
通知が来た場合は、App Store Connectで該当アプリの予約注文リリース予定日を確認してください。

定期実行時刻を変更する場合は `.github/workflows/appstore-moniter.yml` の
`cron` を変更します。GitHub ActionsのcronはUTCのため、日本時間9:00に実行したい場合は
`0 0 * * *` を指定します。

## 9. システムの停止と再起動

停止する場合:

1. GitHub Enterpriseのリポジトリを開きます。
2. **「Actions」** を開きます。
3. **「App Store Moniter」** workflowを無効化します。

再起動する場合:

1. **「Actions」** を開きます。
2. 無効化したworkflowを有効化します。
3. **「Run workflow」** で手動実行します。

## 10. 困ったときは

### 症状: Slackに通知が届かない

確認 1: Slack Botがチャンネルに参加しているか確認してください。

確認 2: `SLACK_BOT_TOKEN` がGitHub Secretsに登録されているか確認してください。

確認 3: Actionsログに `Slack notification failed` が出ていないか確認してください。

### 症状: App Store Connect APIで失敗する

確認 1: `APPSTORE_ISSUER_ID`、`APPSTORE_KEY_ID`、`APPSTORE_PRIVATE_KEY` を確認してください。

確認 2: `.p8` ファイルの中身を改行込みでSecretへ登録しているか確認してください。

確認 3: APIキーの権限がアプリ情報を参照できる権限か確認してください。

### 症状: Actionsが実行されない

確認 1: GitHub EnterpriseでActionsが有効か確認してください。

確認 2: `.github/workflows/appstore-moniter.yml` がmainブランチにあるか確認してください。

確認 3: GitHub Enterprise Serverの場合、Runnerが外部通信できるか確認してください。

自力で解決できない場合は、Actionsの失敗ログ、実行日時、通知先チャンネル名を添えて
リポジトリ管理者へ連絡してください。

## 11. 用語集

| 用語 | 説明 |
| --- | --- |
| App Store Connect API | App Store Connectの情報をプログラムから取得する仕組み |
| APIキー | APIを使うための認証情報 |
| `.p8` ファイル | App Store Connect APIで使う秘密鍵ファイル |
| Slack Bot Token | SlackへBotとして投稿するための認証情報 |
| GitHub Secrets | GitHub Actionsで使う秘密情報を安全に保存する機能 |
| GitHub Actions | GitHub上で定期実行や自動処理を行う機能 |
| Runner | GitHub Actionsの処理を実行するコンピューター |
