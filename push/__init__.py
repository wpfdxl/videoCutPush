# -*- coding: utf-8 -*-
"""
推送模块：合并后可选择推送到各视频平台（如 B 站）。
模块化设计，后续可扩展其他平台（如抖音、YouTube 等）。
"""
from __future__ import absolute_import

_REGISTRY = {}

def register(name):
    """装饰器：将推送实现注册到 REGISTRY。"""
    def _wrap(cls):
        _REGISTRY[name] = cls
        return cls
    return _wrap


def get_pusher(name, **kwargs):
    """
    根据平台名获取推送客户端。
    :param name: 平台标识，如 'bilibili'
    :param kwargs: 传给该平台构造函数的参数（如 cookie_path、config 等）
    :return: 该平台的 PusherBase 实例
    """
    if name not in _REGISTRY:
        raise ValueError("未知推送平台: {}，可选: {}".format(name, list(_REGISTRY.keys())))
    return _REGISTRY[name](**kwargs)


def list_platforms():
    """返回已注册的推送平台列表。"""
    return list(_REGISTRY.keys())


# 注册 bilibili，避免顶层 import 时未加载子模块
def _register_builtin():
    try:
        from .bilibili import BilibiliPusher
        _REGISTRY["bilibili"] = BilibiliPusher
    except ImportError:
        pass


_register_builtin()
