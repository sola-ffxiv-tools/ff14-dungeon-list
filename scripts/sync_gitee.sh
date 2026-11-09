#!/usr/bin/env bash
# 把当前 HEAD 镜像到 Gitee 仓库。
#
# 目标仓库、认证账号全部来自环境变量，方便 fork 后自行配置；未配置时跳过（不算失败）：
#   GITEE_TOKEN   必填，Gitee 私人令牌（仓库读写权限）
#   GITEE_USER    必填，令牌所属账号（需对目标仓库有写权限）
#   GITEE_OWNER   必填，目标仓库的命名空间（个人用户名或组织名）
#   GITEE_REPO    必填，目标仓库名
#   GITEE_BRANCH  可选，默认 main
#
# 先比对远端 SHA：一致就什么都不做（幂等、无副作用），不一致才 force push，
# 这样上一次同步失败也能在下次运行自动补齐。
set -euo pipefail

missing=()
[ -z "${GITEE_TOKEN:-}" ] && missing+=("GITEE_TOKEN")
[ -z "${GITEE_USER:-}" ] && missing+=("GITEE_USER")
[ -z "${GITEE_OWNER:-}" ] && missing+=("GITEE_OWNER")
[ -z "${GITEE_REPO:-}" ] && missing+=("GITEE_REPO")

if [ "${#missing[@]}" -gt 0 ]; then
  echo "::warning::Gitee 配置不完整（缺少 ${missing[*]}），跳过同步"
  exit 0
fi

branch="${GITEE_BRANCH:-main}"
remote_url="https://${GITEE_USER}:${GITEE_TOKEN}@gitee.com/${GITEE_OWNER}/${GITEE_REPO}.git"
local_sha="$(git rev-parse HEAD)"
remote_sha="$(git ls-remote --heads "${remote_url}" "refs/heads/${branch}" | awk '{print $1}' | head -n 1)"

if [ -n "${remote_sha}" ] && [ "${remote_sha}" = "${local_sha}" ]; then
  echo "Gitee ${GITEE_OWNER}/${GITEE_REPO}@${branch} 已与 GitHub 一致（${local_sha:0:7}），无需推送"
  exit 0
fi

echo "同步 Gitee ${GITEE_OWNER}/${GITEE_REPO}@${branch}: ${remote_sha:-<empty>} -> ${local_sha:0:7}"
git push --force "${remote_url}" "HEAD:refs/heads/${branch}"
git push --force "${remote_url}" --tags
echo "Gitee 同步完成"
