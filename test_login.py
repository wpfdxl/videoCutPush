#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 B 站扫码登录并获取 access_token"""

from push.bilibili.client import BilibiliPusher

def test_login():
    print("测试 B 站扫码登录...")
    pusher = BilibiliPusher(cookie_path="push/bilibili/cookie.json")
    
    if pusher.is_logged_in():
        print("✓ 已登录，Cookie 有效")
        if pusher._access_token:
            print("✓ 已有 access_token，将使用 APP 接口投稿")
        else:
            print("⚠ 无 access_token，将使用 Web 接口投稿")
        return
    
    print("开始扫码登录...")
    success = pusher.login(use_qrcode=True)
    
    if success:
        print("✓ 登录成功！")
        if pusher._access_token:
            print("✓ 已获取 access_token，将使用 APP 接口投稿")
            print("  access_token 前10位: {}...".format(pusher._access_token[:10]))
        else:
            print("⚠ 未获取到 access_token，将使用 Web 接口投稿")
        print("✓ Cookie 已保存到: push/bilibili/cookie.json")
    else:
        print("✗ 登录失败")

if __name__ == "__main__":
    test_login()
