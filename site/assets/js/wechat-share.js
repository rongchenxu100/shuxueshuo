/**
 * 微信内置浏览器：加载 JS-SDK，请求同源签名接口后配置「分享给朋友 / 朋友圈」。
 * 文案与配图来源：meta[property="wechat:share:image"]（可选）> og:* > meta description > document.title。
 */
(function () {
  "use strict";

  var WX_JS = "https://res.wx.qq.com/open/js/jweixin-1.6.0.js";
  var UA = typeof navigator !== "undefined" ? navigator.userAgent || "" : "";

  if (!/MicroMessenger/i.test(UA)) {
    return;
  }

  function readMeta(property) {
    var el = document.querySelector('meta[property="' + property + '"]');
    return el && el.getAttribute("content") ? el.getAttribute("content").trim() : "";
  }

  function readMetaName(name) {
    var el = document.querySelector('meta[name="' + name + '"]');
    return el && el.getAttribute("content") ? el.getAttribute("content").trim() : "";
  }

  function parseJsonConfig() {
    var el = document.getElementById("wechat-share-config");
    if (!el || el.type !== "application/json") return null;
    try {
      return JSON.parse(el.textContent || "{}");
    } catch (e) {
      return null;
    }
  }

  function absoluteUrl(u) {
    if (!u) return "";
    try {
      return new URL(u, window.location.href).href;
    } catch (err) {
      return u;
    }
  }

  function signEndpoint() {
    var fromHtml = document.documentElement.getAttribute("data-wechat-sign-url");
    if (fromHtml && fromHtml.trim()) return fromHtml.trim();
    return "/api/wechat/jssdk-config";
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.async = true;
      s.src = src;
      s.onload = function () {
        resolve();
      };
      s.onerror = function () {
        reject(new Error("Failed to load " + src));
      };
      document.head.appendChild(s);
    });
  }

  function pickSharePayload() {
    var json = parseJsonConfig() || {};
    var link = window.location.href.split("#")[0];
    var title =
      json.title ||
      readMeta("og:title") ||
      (document.title || "").trim() ||
      "数学说";
    var desc =
      json.desc ||
      readMeta("og:description") ||
      readMetaName("description") ||
      title;
    var imgRaw =
      json.imgUrl ||
      readMeta("wechat:share:image") ||
      readMeta("og:image") ||
      "";
    var imgUrl = absoluteUrl(imgRaw);
    var payload = {
      title: title,
      desc: desc,
      link: json.link || link,
      imgUrl: imgUrl,
    };
    return payload;
  }

  function runWx(payload) {
    if (!window.wx || !window.wx.config) {
      return;
    }
    var pageUrl = window.location.href.split("#")[0];
    var api = signEndpoint();
    var url = api + (api.indexOf("?") >= 0 ? "&" : "?") + "url=" + encodeURIComponent(pageUrl);

    fetch(url, { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("sign http " + r.status);
        return r.json();
      })
      .then(function (cfg) {
        window.wx.config({
          debug: false,
          appId: cfg.appId,
          timestamp: cfg.timestamp,
          nonceStr: cfg.nonceStr,
          signature: cfg.signature,
          jsApiList: ["updateAppMessageShareData", "updateTimelineShareData"],
        });
        window.wx.ready(function () {
          window.wx.updateAppMessageShareData({
            title: payload.title,
            desc: payload.desc,
            link: payload.link,
            imgUrl: payload.imgUrl,
          });
          window.wx.updateTimelineShareData({
            title: payload.title,
            link: payload.link,
            imgUrl: payload.imgUrl,
          });
        });
        window.wx.error(function (err) {
          if (typeof console !== "undefined" && console.warn) {
            console.warn("[wechat-share] wx.error", err);
          }
        });
      })
      .catch(function (err) {
        if (typeof console !== "undefined" && console.warn) {
          console.warn("[wechat-share] init failed", err);
        }
      });
  }

  loadScript(WX_JS)
    .then(function () {
      runWx(pickSharePayload());
    })
    .catch(function (err) {
      if (typeof console !== "undefined" && console.warn) {
        console.warn("[wechat-share]", err);
      }
    });
})();
