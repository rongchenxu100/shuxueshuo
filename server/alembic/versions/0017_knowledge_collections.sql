-- A collection groups knowledge independently of a textbook chapter, for example
-- junior-school prerequisites reused by several senior-school chapters.
ALTER TABLE knowledge_nodes DROP CONSTRAINT knowledge_nodes_kind_check;
ALTER TABLE knowledge_nodes ADD CONSTRAINT knowledge_nodes_kind_check
 CHECK(kind IN ('textbook','chapter','section','collection','knowledge','skill','method','problem_type','judgment_rule'));
