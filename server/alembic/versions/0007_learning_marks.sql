CREATE TABLE student_learning_marks (
    user_id uuid NOT NULL REFERENCES users(id),
    problem_id text NOT NULL,
    practiced boolean NOT NULL DEFAULT false,
    learning_status text NOT NULL DEFAULT 'unmarked',
    PRIMARY KEY (user_id, problem_id),
    CONSTRAINT ck_learning_status CHECK (learning_status IN ('unmarked','mastered','needs_review')),
    CONSTRAINT ck_learning_practiced CHECK (practiced OR learning_status = 'unmarked')
);
