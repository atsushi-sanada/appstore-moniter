"""App Store予約注文中アプリのリリース予定日をSlack通知するCLIツール。

会社単位でApp Store Connect APIから全アプリを取得し、予約注文が有効な
アプリのリリース予定日が通知対象日数以内ならSlackチャンネルへ通知する。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path("config/settings.json")
DEFAULT_STATE_PATH = Path(".appstore_moniter_state.json")
DEFAULT_NOTIFY_DAYS = 7
DEFAULT_POLL_TIME = "09:00"
DEFAULT_API_BASE_URL = "https://api.appstoreconnect.apple.com"
APP_STORE_CONNECT_AUDIENCE = "appstoreconnect-v1"
SLACK_API_URL = "https://slack.com/api/chat.postMessage"


@dataclass(frozen=True)
class AppStoreConnectConfig:
    """App Store Connect API認証設定。"""

    issuer_id: str
    key_id: str
    private_key_path: Path
    api_base_url: str


@dataclass(frozen=True)
class SlackConfig:
    """Slack通知設定。"""

    bot_token: str
    channel: str


@dataclass(frozen=True)
class CompanyConfig:
    """会社単位の監視設定。"""

    company_code: str
    notify_days: int
    poll_time: str
    app_store_connect: AppStoreConnectConfig | None
    slack: SlackConfig | None
    fixture_apps: list[dict[str, Any]]


@dataclass(frozen=True)
class AppSummary:
    """App Store Connect上のアプリ基本情報。"""

    app_id: str
    name: str
    bundle_id: str


@dataclass(frozen=True)
class PreOrderApp:
    """予約注文中アプリのリリース予定日情報。"""

    company_code: str
    app_id: str
    name: str
    bundle_id: str
    release_date: date
    territories: tuple[str, ...]
    content_statuses: tuple[str, ...]


@dataclass(frozen=True)
class NotificationTarget:
    """通知対象アプリと予定日までの日数。"""

    app: PreOrderApp
    days_until_release: int


class AppStoreConnectClient:
    """App Store Connect APIからアプリと予約注文情報を取得するクライアント。"""

    def __init__(self, config: AppStoreConnectConfig) -> None:
        """APIクライアントを初期化する。

        Args:
            config: App Store Connect API認証設定。
        """

        self._config = config
        self._token = CreateAppStoreConnectToken(config)

    def FetchApps(self) -> list[AppSummary]:
        """会社アカウントで参照可能な全アプリを取得する。

        Returns:
            アプリ基本情報一覧。
        """

        params = {
            "fields[apps]": "name,bundleId",
            "limit": "200",
        }
        data = self._GetJson("/v1/apps", params)
        apps = ParseApps(data)

        while isinstance(data.get("links"), dict) and data["links"].get("next"):
            data = self._GetJson(str(data["links"]["next"]), {})
            apps.extend(ParseApps(data))

        return apps

    def FetchPreOrderApp(
        self,
        company_code: str,
        app: AppSummary,
    ) -> PreOrderApp | None:
        """指定アプリが予約注文中ならリリース予定日情報を返す。

        Args:
            company_code: 通知に表示する会社コード。
            app: アプリ基本情報。

        Returns:
            予約注文中アプリ情報。予約注文中でなければNone。
        """

        params = {
            "include": "territoryAvailabilities",
            "fields[territoryAvailabilities]": (
                "available,preOrderEnabled,releaseDate,preOrderPublishDate,"
                "contentStatuses,territory"
            ),
            "limit[territoryAvailabilities]": "50",
        }
        try:
            data = self._GetJson(f"/v1/apps/{app.app_id}/appAvailabilityV2", params)
        except AppStoreConnectApiError as error:
            if error.status == 404:
                return None
            raise

        return ParsePreOrderApp(company_code, app, data)

    def _GetJson(self, path_or_url: str, params: dict[str, str]) -> dict[str, Any]:
        """App Store Connect APIからJSONを取得する。

        Args:
            path_or_url: APIパスまたは絶対URL。
            params: クエリパラメータ。

        Returns:
            レスポンスJSON。
        """

        url = BuildUrl(self._config.api_base_url, path_or_url, params)
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self._token}"},
            method="GET",
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise AppStoreConnectApiError(error.code, body) from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"App Store Connect API failed: {error}") from error


class AppStoreConnectApiError(RuntimeError):
    """App Store Connect APIのHTTPエラー。"""

    def __init__(self, status: int, body: str) -> None:
        """HTTPステータスとレスポンス本文を保持する。

        Args:
            status: HTTPステータスコード。
            body: エラーレスポンス本文。
        """

        super().__init__(f"App Store Connect API failed: {body}")
        self.status = status


def CreateAppStoreConnectToken(config: AppStoreConnectConfig) -> str:
    """App Store Connect API用JWTを生成する。

    Args:
        config: App Store Connect API認証設定。

    Returns:
        JWT文字列。

    Raises:
        RuntimeError: PyJWTまたは秘密鍵の読み込みに失敗した場合。
    """

    try:
        import jwt
    except ImportError as error:
        raise RuntimeError(
            "PyJWT is required. Install dependencies with pip install -r "
            "requirements.txt."
        ) from error

    now = int(time.time())
    payload = {
        "iss": config.issuer_id,
        "aud": APP_STORE_CONNECT_AUDIENCE,
        "iat": now,
        "exp": now + 20 * 60,
    }
    headers = {
        "alg": "ES256",
        "kid": config.key_id,
        "typ": "JWT",
    }

    private_key = config.private_key_path.read_text(encoding="utf-8")
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    return str(token)


def BuildUrl(base_url: str, path_or_url: str, params: dict[str, str]) -> str:
    """APIリクエストURLを組み立てる。

    Args:
        base_url: APIベースURL。
        path_or_url: APIパスまたは絶対URL。
        params: クエリパラメータ。

    Returns:
        リクエストURL。
    """

    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        return path_or_url

    query = urllib.parse.urlencode(params)
    path = path_or_url if path_or_url.startswith("/") else f"/{path_or_url}"
    return f"{base_url.rstrip('/')}{path}?{query}" if query else f"{base_url}{path}"


def ParseApps(data: dict[str, Any]) -> list[AppSummary]:
    """App Store Connect APIのアプリ一覧レスポンスを変換する。

    Args:
        data: APIレスポンスJSON。

    Returns:
        アプリ基本情報一覧。
    """

    apps: list[AppSummary] = []
    for item in data.get("data", []):
        attributes = item.get("attributes", {})
        apps.append(
            AppSummary(
                app_id=str(item["id"]),
                name=str(attributes.get("name", "")),
                bundle_id=str(attributes.get("bundleId", "")),
            )
        )

    return apps


def ParsePreOrderApp(
    company_code: str,
    app: AppSummary,
    data: dict[str, Any],
) -> PreOrderApp | None:
    """App Availabilityレスポンスから予約注文中アプリ情報を抽出する。

    Args:
        company_code: 通知に表示する会社コード。
        app: アプリ基本情報。
        data: App Availability APIレスポンスJSON。

    Returns:
        予約注文中アプリ情報。対象外ならNone。
    """

    release_dates: list[date] = []
    territories: list[str] = []
    statuses: set[str] = set()

    for item in data.get("included", []):
        if item.get("type") != "territoryAvailabilities":
            continue

        attributes = item.get("attributes", {})
        content_statuses = attributes.get("contentStatuses", [])
        if isinstance(content_statuses, list):
            statuses.update(str(status) for status in content_statuses)

        if not IsPreOrderTerritory(attributes):
            continue

        raw_release_date = attributes.get("releaseDate")
        if not isinstance(raw_release_date, str) or not raw_release_date:
            continue

        release_dates.append(ParseDate(raw_release_date))
        territories.append(ExtractTerritoryCode(item))

    if not release_dates:
        return None

    return PreOrderApp(
        company_code=company_code,
        app_id=app.app_id,
        name=app.name,
        bundle_id=app.bundle_id,
        release_date=min(release_dates),
        territories=tuple(sorted(set(territories))),
        content_statuses=tuple(sorted(statuses)),
    )


def IsPreOrderTerritory(attributes: dict[str, Any]) -> bool:
    """テリトリが予約注文中か判定する。

    Args:
        attributes: territoryAvailabilitiesのattributes。

    Returns:
        予約注文中ならTrue。
    """

    content_statuses = attributes.get("contentStatuses", [])
    if attributes.get("preOrderEnabled") is True:
        return True
    if not isinstance(content_statuses, list):
        return False

    return "AVAILABLE_FOR_PREORDER" in [str(status) for status in content_statuses]


def ExtractTerritoryCode(item: dict[str, Any]) -> str:
    """territoryAvailabilityから国・地域コードを抽出する。

    Args:
        item: territoryAvailabilityのJSONオブジェクト。

    Returns:
        国・地域コード。取得できない場合はunknown。
    """

    territory = (
        item.get("relationships", {})
        .get("territory", {})
        .get("data", {})
    )
    return str(territory.get("id", "unknown"))


def ParseDate(value: str) -> date:
    """YYYY-MM-DD形式またはISO日時文字列を日付へ変換する。

    Args:
        value: 日付文字列。

    Returns:
        変換後の日付。
    """

    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def LoadConfig(config_path: Path) -> CompanyConfig:
    """設定ファイルから会社単位の監視設定を読み込む。

    Args:
        config_path: JSON設定ファイルのパス。

    Returns:
        会社単位の監視設定。
    """

    with config_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    company_code = RequireString(data, "company_code")
    notify_days = int(data.get("notify_days", DEFAULT_NOTIFY_DAYS))
    poll_time = str(data.get("poll_time", DEFAULT_POLL_TIME))
    fixture_apps = data.get("fixture_apps", [])
    if not isinstance(fixture_apps, list):
        raise ValueError("fixture_apps must be an array.")

    return CompanyConfig(
        company_code=company_code,
        notify_days=notify_days,
        poll_time=poll_time,
        app_store_connect=LoadAppStoreConnectConfig(data),
        slack=LoadSlackConfig(data),
        fixture_apps=fixture_apps,
    )


def LoadAppStoreConnectConfig(
    data: dict[str, Any],
) -> AppStoreConnectConfig | None:
    """App Store Connect API設定を読み込む。

    Args:
        data: 設定JSON。

    Returns:
        API設定。未設定ならNone。
    """

    raw_config = data.get("app_store_connect")
    if raw_config is None:
        return None
    if not isinstance(raw_config, dict):
        raise ValueError("app_store_connect must be an object.")

    issuer_id = ReadConfigSecret(raw_config, "issuer_id", "issuer_id_env")
    key_id = ReadConfigSecret(raw_config, "key_id", "key_id_env")
    private_key_path = ReadConfigSecret(
        raw_config,
        "private_key_path",
        "private_key_path_env",
    )
    api_base_url = str(raw_config.get("api_base_url", DEFAULT_API_BASE_URL))

    return AppStoreConnectConfig(
        issuer_id=issuer_id,
        key_id=key_id,
        private_key_path=Path(private_key_path),
        api_base_url=api_base_url,
    )


def LoadSlackConfig(data: dict[str, Any]) -> SlackConfig | None:
    """Slack通知設定を読み込む。

    Args:
        data: 設定JSON。

    Returns:
        Slack通知設定。未設定ならNone。
    """

    raw_config = data.get("slack")
    if raw_config is None:
        return None
    if not isinstance(raw_config, dict):
        raise ValueError("slack must be an object.")

    return SlackConfig(
        bot_token=ReadConfigSecret(raw_config, "bot_token", "bot_token_env"),
        channel=RequireString(raw_config, "channel"),
    )


def RequireString(data: dict[str, Any], key: str) -> str:
    """設定値から必須文字列を取得する。

    Args:
        data: 設定JSON。
        key: 取得キー。

    Returns:
        設定文字列。
    """

    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"config requires a non-empty string: {key}")

    return value.strip()


def ReadConfigSecret(
    data: dict[str, Any],
    direct_key: str,
    env_key: str,
) -> str:
    """設定ファイルまたは環境変数から秘密情報を取得する。

    環境変数名が設定済みで値が未設定の場合は、API実行やSlack通知まで
    エラーにしない。fixture実行では外部サービスの秘密情報を不要にするため。

    Args:
        data: 設定JSON。
        direct_key: 直接指定キー。
        env_key: 環境変数名を保持するキー。

    Returns:
        秘密情報。
    """

    if isinstance(data.get(direct_key), str) and data[direct_key].strip():
        return str(data[direct_key]).strip()

    env_name = data.get(env_key)
    if not isinstance(env_name, str) or not env_name.strip():
        raise ValueError(f"config requires {direct_key} or {env_key}.")

    return os.environ.get(env_name.strip(), "")


def ValidateAppStoreConnectConfig(config: AppStoreConnectConfig) -> None:
    """App Store Connect API実行に必要な秘密情報を検証する。

    Args:
        config: App Store Connect API認証設定。

    Raises:
        ValueError: 必須設定が不足している場合。
    """

    missing_keys: list[str] = []
    if not config.issuer_id:
        missing_keys.append("APPSTORE_ISSUER_ID")
    if not config.key_id:
        missing_keys.append("APPSTORE_KEY_ID")
    if not str(config.private_key_path):
        missing_keys.append("APPSTORE_PRIVATE_KEY_PATH")

    if missing_keys:
        raise ValueError(
            "environment variables are required: " + ", ".join(missing_keys)
        )


def ValidateSlackConfig(config: SlackConfig) -> None:
    """Slack通知に必要な秘密情報を検証する。

    Args:
        config: Slack通知設定。

    Raises:
        ValueError: 必須設定が不足している場合。
    """

    if not config.bot_token:
        raise ValueError("environment variable is required: SLACK_BOT_TOKEN")


def FetchPreOrderApps(config: CompanyConfig, source: str) -> list[PreOrderApp]:
    """予約注文中アプリ一覧を取得する。

    Args:
        config: 会社単位の監視設定。
        source: 取得元。apiまたはfixture。

    Returns:
        予約注文中アプリ一覧。
    """

    if source == "fixture":
        return [CreateFixturePreOrderApp(config.company_code, app) for app in config.fixture_apps]

    if config.app_store_connect is None:
        raise ValueError("app_store_connect config is required for api source.")

    ValidateAppStoreConnectConfig(config.app_store_connect)
    client = AppStoreConnectClient(config.app_store_connect)
    pre_order_apps: list[PreOrderApp] = []
    for app in client.FetchApps():
        pre_order_app = client.FetchPreOrderApp(config.company_code, app)
        if pre_order_app is not None:
            pre_order_apps.append(pre_order_app)

    return pre_order_apps


def CreateFixturePreOrderApp(
    company_code: str,
    raw_app: dict[str, Any],
) -> PreOrderApp:
    """検証用設定から予約注文中アプリを生成する。

    Args:
        company_code: 会社コード。
        raw_app: 検証用アプリ設定。

    Returns:
        予約注文中アプリ。
    """

    territories = raw_app.get("territories", [])
    if not isinstance(territories, list):
        raise ValueError("fixture app territories must be an array.")

    return PreOrderApp(
        company_code=company_code,
        app_id=RequireString(raw_app, "app_id"),
        name=RequireString(raw_app, "name"),
        bundle_id=RequireString(raw_app, "bundle_id"),
        release_date=ParseDate(RequireString(raw_app, "release_date")),
        territories=tuple(str(territory) for territory in territories),
        content_statuses=("AVAILABLE_FOR_PREORDER",),
    )


def LoadState(state_path: Path) -> dict[str, str]:
    """通知済み状態を読み込む。

    Args:
        state_path: 状態ファイルのパス。

    Returns:
        通知キーごとの最終通知日。
    """

    if not state_path.exists():
        return {}

    with state_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict):
        raise ValueError("state file must be a JSON object.")

    return {str(key): str(value) for key, value in data.items()}


def SaveState(state_path: Path, state: dict[str, str]) -> None:
    """通知済み状態を保存する。

    Args:
        state_path: 状態ファイルのパス。
        state: 通知キーごとの最終通知日。
    """

    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def BuildNotificationTargets(
    apps: list[PreOrderApp],
    today: date,
    notify_days: int,
    state: dict[str, str],
) -> list[NotificationTarget]:
    """本日通知すべき予約注文中アプリを抽出する。

    Args:
        apps: 予約注文中アプリ一覧。
        today: 判定対象日。
        notify_days: 何日前から通知するか。
        state: 通知キーごとの最終通知日。

    Returns:
        通知対象一覧。
    """

    today_key = today.isoformat()
    targets: list[NotificationTarget] = []

    for app in apps:
        days_until_release = (app.release_date - today).days
        if state.get(CreateStateKey(app)) == today_key:
            continue
        if 0 <= days_until_release <= notify_days:
            targets.append(NotificationTarget(app, days_until_release))

    return targets


def CreateStateKey(app: PreOrderApp) -> str:
    """通知済み状態のキーを作成する。

    Args:
        app: 予約注文中アプリ。

    Returns:
        状態管理キー。
    """

    return f"{app.company_code}:{app.app_id}:{app.release_date.isoformat()}"


def BuildMessage(targets: list[NotificationTarget], today: date) -> str:
    """Slack通知本文を作成する。

    Args:
        targets: 通知対象一覧。
        today: 通知日。

    Returns:
        通知本文。
    """

    lines = [
        ":warning: App Store予約注文のリリース予定日が近づいています。",
        f"確認日: {today.isoformat()}",
        "",
    ]

    for target in targets:
        app = target.app
        territories = ", ".join(app.territories) if app.territories else "unknown"
        lines.append(
            f"- [{app.company_code}] {app.name} ({app.bundle_id}) "
            f"release={app.release_date.isoformat()} "
            f"remaining={target.days_until_release} days territories={territories}"
        )

    lines.extend(
        [
            "",
            "App Store Connectで予約注文のリリース予定日を確認してください。",
        ]
    )
    return "\n".join(lines)


def NotifyToStdout(message: str) -> None:
    """標準出力へ通知内容を表示する。

    Args:
        message: 通知本文。
    """

    print(message)


def NotifyToSlack(message: str, config: SlackConfig) -> None:
    """Slackチャンネルへ通知する。

    Args:
        message: 通知本文。
        config: Slack通知設定。
    """

    payload = json.dumps(
        {
            "channel": config.channel,
            "text": message,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        SLACK_API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {config.bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as error:
        raise RuntimeError(f"Slack notification failed: {error}") from error

    if data.get("ok") is not True:
        raise RuntimeError(f"Slack notification failed: {data}")


def RunOnce(args: argparse.Namespace) -> int:
    """ポーリングと通知を1回実行する。

    Args:
        args: CLI引数。

    Returns:
        終了コード。
    """

    today = ParseDate(args.today) if args.today else date.today()
    config_path = Path(args.config)
    state_path = Path(args.state)

    try:
        config = LoadConfig(config_path)
        notify_days = args.notify_days if args.notify_days is not None else config.notify_days
        if notify_days < 0:
            print("--notify-days must be zero or greater.", file=sys.stderr)
            return 2

        pre_order_apps = FetchPreOrderApps(config, args.source)
        state = LoadState(state_path)
        targets = BuildNotificationTargets(pre_order_apps, today, notify_days, state)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"Failed to run checker: {error}", file=sys.stderr)
        return 1

    if not targets:
        print("No apps need notification today.")
        return 0

    message = BuildMessage(targets, today)

    try:
        if args.notify == "slack":
            if config.slack is None:
                print("slack config is required for Slack notification.", file=sys.stderr)
                return 2
            ValidateSlackConfig(config.slack)
            NotifyToSlack(message, config.slack)
        else:
            NotifyToStdout(message)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1

    if not args.dry_run:
        today_key = today.isoformat()
        for target in targets:
            state[CreateStateKey(target.app)] = today_key
        SaveState(state_path, state)

    return 0


def RunDaemon(args: argparse.Namespace) -> int:
    """設定された時刻に毎日ポーリングする常駐実行。

    Args:
        args: CLI引数。

    Returns:
        終了コード。
    """

    config = LoadConfig(Path(args.config))
    while True:
        next_run = CalculateNextRun(datetime.now(), config.poll_time)
        sleep_seconds = max(1, int((next_run - datetime.now()).total_seconds()))
        print(f"Next polling time: {next_run.isoformat(timespec='seconds')}")
        time.sleep(sleep_seconds)
        exit_code = RunOnce(args)
        if exit_code != 0:
            print(f"Polling failed with exit code {exit_code}.", file=sys.stderr)


def CalculateNextRun(now: datetime, poll_time: str) -> datetime:
    """次回実行時刻を計算する。

    Args:
        now: 現在時刻。
        poll_time: HH:MM形式の実行時刻。

    Returns:
        次回実行日時。
    """

    hour_text, minute_text = poll_time.split(":", maxsplit=1)
    next_run = now.replace(
        hour=int(hour_text),
        minute=int(minute_text),
        second=0,
        microsecond=0,
    )
    if next_run <= now:
        next_run += timedelta(days=1)

    return next_run


def ParseArgs(argv: list[str]) -> argparse.Namespace:
    """CLI引数を解析する。

    Args:
        argv: コマンドライン引数。

    Returns:
        解析済み引数。
    """

    parser = argparse.ArgumentParser(
        description="App Store予約注文中アプリを毎日ポーリングしてSlack通知します。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python src/appstore_moniter.py --source fixture --dry-run\n"
            "  python src/appstore_moniter.py --notify slack\n"
            "  python src/appstore_moniter.py --daemon --notify slack\n"
        ),
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="監視設定JSONパス（デフォルト: config/settings.json）",
    )
    parser.add_argument(
        "--state",
        default=str(DEFAULT_STATE_PATH),
        help="通知済み状態ファイルのパス",
    )
    parser.add_argument(
        "--notify-days",
        type=int,
        help="何日前から通知するか。省略時は設定ファイルの値を使用",
    )
    parser.add_argument(
        "--notify",
        choices=("stdout", "slack"),
        default="stdout",
        help="通知先（デフォルト: stdout）",
    )
    parser.add_argument(
        "--source",
        choices=("api", "fixture"),
        default="api",
        help="アプリ情報の取得元（デフォルト: api）",
    )
    parser.add_argument(
        "--today",
        help="検証用の日付 YYYY-MM-DD（省略時は実行日）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="通知済み状態を更新せず、通知内容だけ表示する",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="設定ファイルのpoll_timeに毎日実行する常駐モード",
    )
    return parser.parse_args(argv)


def Main(argv: list[str] | None = None) -> int:
    """CLIエントリポイント。

    Args:
        argv: コマンドライン引数。

    Returns:
        終了コード。
    """

    args = ParseArgs(argv or sys.argv[1:])
    if args.daemon:
        return RunDaemon(args)

    return RunOnce(args)


if __name__ == "__main__":
    raise SystemExit(Main())
