-- tipsff14 / transcript_content
-- 字段对齐 static/data/maze.json：
--   title: 大分类标题
--   list : 副本列表 JSON，元素形如 {"title":"副本名"}

CREATE DATABASE IF NOT EXISTS `tipsff14`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `tipsff14`;

CREATE TABLE IF NOT EXISTS `transcript_content` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `title` VARCHAR(128) NOT NULL COMMENT '大分类标题，对应 json 顶层 title',
  `list` JSON NOT NULL COMMENT '副本列表，对应 json 的 list，元素为 {"title":"..."}',
  `source` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '数据来源：huiji_wiki / garlandtools / local_fallback',
  `scraped_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '本次爬取时间',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '首次入库时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_title` (`title`)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='副本分类与副本名（与 maze.json 结构一致）';
