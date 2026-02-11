# -*- coding: utf-8 -*-
"""
推送基类：定义登录、上传等接口，各平台实现此类。
"""
from __future__ import absolute_import


class PusherBase(object):
    """推送基类，各平台需实现 login / is_logged_in / upload。"""

    def login(self, **kwargs):
        """
        执行登录（Cookie、扫码、密码等由各平台实现）。
        :return: True 表示成功
        """
        raise NotImplementedError

    def is_logged_in(self):
        """检查当前是否已登录。"""
        raise NotImplementedError

    def upload(self, video_path, title, desc="", **kwargs):
        """
        上传单个视频。
        :param video_path: 本地视频文件路径
        :param title: 标题
        :param desc: 简介/描述
        :param kwargs: 平台扩展参数（如 tid、tag、cover、dtime 等）
        :return: 平台返回的投稿结果（如 aid、bv 等），具体由平台定义
        """
        raise NotImplementedError
