"""Request-local read accounting and original-backed entity seeds for research.

No cache or authority state survives a request. The parent still owns the hard
wall deadline; these limits bound SQL duration and materialized work within it.
"""
from contextlib import contextmanager
import re

LIMITS = dict(sql_statements=384, entity_resolutions=4, graph_seeds_per_step=3,
              neighbors_per_seed=8, hops=3, documents=24, chunks_per_document=64,
              candidate_documents=24)


class ReadLimit(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class _Cursor:
    def __init__(self, cursor, guard):
        self._cursor, self._guard = cursor, guard

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __enter__(self):
        self._cursor.__enter__()
        return self

    def __exit__(self, *args):
        return self._cursor.__exit__(*args)

    def __iter__(self):
        return iter(self._cursor)

    def execute(self, *args, **kwargs):
        self._guard.charge()
        self._cursor.execute(*args, **kwargs)
        return self


class ResearchReads:
    def __init__(self, conn, state, budget, started, clock):
        self._conn, self.state, self.budget = conn, state, budget
        self.started, self.clock, self.exhausted = started, clock, None

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def charge(self):
        if self.clock()-self.started >= self.budget.seconds:
            self.exhausted = 'time_budget'
        elif self.state['exploration']['sql_statements'] >= LIMITS['sql_statements']:
            self.exhausted = 'sql_budget'
        if self.exhausted:
            raise ReadLimit(self.exhausted)
        self.state['exploration']['sql_statements'] += 1

    def execute(self, *args, **kwargs):
        self.charge()
        return self._conn.execute(*args, **kwargs)

    def cursor(self, *args, **kwargs):
        return _Cursor(self._conn.cursor(*args, **kwargs), self)

    @contextmanager
    def operation(self):
        # Control statements are included in the SQL count. Use the underlying
        # connection only to restore settings even when the work limit is spent.
        remaining = self.budget.seconds - (self.clock()-self.started)
        if remaining <= 0:
            self.exhausted = 'time_budget'
            raise ReadLimit(self.exhausted)
        prior = self.execute("SELECT current_setting('statement_timeout') s, "
                             "current_setting('lock_timeout') l").fetchone()
        values = self.execute("SELECT name,setting::int value FROM pg_settings "
                              "WHERE name IN ('statement_timeout','lock_timeout')").fetchall()
        for row in values:
            cap = min(5000 if row['name']=='statement_timeout' else 500,
                      max(1, int(remaining*1000)))
            self.execute('SELECT set_config(%s,%s,true)',
                         (row['name'], str(min(row['value'] or cap, cap))))
        yield
        if self.exhausted:
            raise ReadLimit(self.exhausted)
        # The caller's savepoint rolls back both GUC changes and failed SQL on
        # exception. Success restores the exact shorter original settings.
        self.charge()
        self._conn.execute("SELECT set_config('statement_timeout',%s,true),"
                           "set_config('lock_timeout',%s,true)", (prior['s'], prior['l']))


def entity_candidates(conn, question, *, domain, scopes, at, history,filter=None):
    """Exact mentioned names, backed by eligible original assertions/alias claims.

    Do not enumerate a scoped identity catalog: even a readable catalog entry
    can outlive its only source. The resolver remains authoritative for alias
    acceptance, ambiguity and names; discovery never publishes catalog metadata.
    """
    from .metadata import argument
    words = re.findall(r'[\w-]+(?:\.[\w-]+)*', question.casefold())[:160]
    names = list(dict.fromkeys(' '.join(words[i:i+n])
                 for n in range(1,6) for i in range(len(words)-n+1)))[:512]
    return conn.execute("""WITH backed AS (
        SELECT a.entity name,d.domain,d.project_scope,d.id FROM fact_assertions a
        JOIN documents d ON d.id=a.document_id WHERE lower(a.entity)=ANY(%(names)s)
        UNION
        SELECT i.name,d.domain,d.project_scope,d.id FROM entity_aliases l
        JOIN documents d ON d.id=l.document_id
        JOIN entity_identities i ON (i.id=l.alias_id OR i.id=l.target_id)
          AND i.project_scope=d.project_scope AND i.domain=d.domain
        WHERE lower(i.name)=ANY(%(names)s) AND l.state='accepted' AND l.effective_at<=%(at)s
    ) SELECT DISTINCT b.name,b.domain,b.project_scope FROM backed b JOIN documents d ON d.id=b.id
      WHERE d.status='active' AND b.project_scope<>'unknown'
        AND assertion_eligible(d.id,%(at)s,%(history)s)
        AND (%(domain)s::text IS NULL OR b.domain=%(domain)s)
        AND (%(scopes)s::text[] IS NULL OR b.project_scope=ANY(%(scopes)s))
      AND (%(metadata)s::jsonb IS NULL OR public.rag_metadata_document(d.id,%(metadata)s))
      ORDER BY b.project_scope,b.domain,b.name LIMIT 5""",
      dict(names=names,at=at,history=history,domain=domain,scopes=scopes,metadata=argument(filter))).fetchall()
