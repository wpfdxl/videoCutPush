# -*- coding: utf-8 -*-
"""
推送模块通用：将链接/文本转为二维码图片，用于扫码登录等。
"""
from __future__ import absolute_import

import os


def save_qrcode_image(content, save_path):
    """
    将字符串（如登录链接）生成二维码并保存为图片。
    :param content: 要编码的字符串（URL 或任意文本）
    :param save_path: 保存路径，如 .png
    :return: 成功返回 save_path，失败返回 None（未安装 qrcode 时返回 None）
    """
    try:
        import qrcode
    except ImportError:
        return None
    try:
        qr = qrcode.QRCode(version=1, box_size=10, border=2)
        qr.add_data(content)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        save_path = os.path.abspath(save_path)
        parent = os.path.dirname(save_path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        img.save(save_path)
        return save_path
    except Exception:
        return None
