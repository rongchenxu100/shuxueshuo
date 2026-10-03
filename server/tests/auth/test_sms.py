import json
from dataclasses import replace

import httpx
import pytest

from shuxueshuo_server.auth.sms import AliyunSms, MockSms, SmsUnavailable


def test_send_sms_contract_and_failure_redaction(config, monkeypatch):
    config = replace(
        config,
        mode="aliyun_sms",
        access_key="key",
        access_secret="secret",
        sign_name="数学说",
        template_code="SMS_TEST",
    )
    requests = []

    def post(url, **kwargs):
        requests.append((url, kwargs))
        return httpx.Response(
            200, json={"Code": "OK"}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx, "post", post)
    AliyunSms(config).send("13900000000", "123456", "challenge")
    url, kwargs = requests[0]
    assert url == "https://dysmsapi.aliyuncs.com/" and "?" not in url
    data = kwargs["data"]
    assert data["Action"] == "SendSms"
    assert json.loads(data["TemplateParam"]) == {"code": "123456"}
    assert data["Signature"] and data["SignName"] == "数学说"
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: httpx.Response(
            200,
            json={"Code": "isv.BUSINESS_LIMIT_CONTROL", "Message": "sensitive"},
            request=httpx.Request("POST", url),
        ),
    )
    with pytest.raises(SmsUnavailable) as error:
        AliyunSms(config).send("13900000000", "123456", "challenge")
    assert "sensitive" not in str(error.value)


def test_mock_private_file(tmp_path):
    directory = tmp_path / "sms"
    sms = MockSms(directory)
    sms.send("13900000000", "123456", "challenge")
    assert (directory / "challenge.json").stat().st_mode & 0o077 == 0
    assert directory.stat().st_mode & 0o077 == 0
    assert json.loads((directory / "challenge.json").read_text())["code"] == "123456"
