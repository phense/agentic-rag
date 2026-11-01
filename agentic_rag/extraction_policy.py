"""Versioned, file-configured extraction preferences (RAG-067, feature 6.9).

One strict, bounded version-1 policy file controls which output categories
mining retains, item/text limits and advisory guidance. It never changes
authorization, evidence grounding, claim qualification, pins, auditing, the
structured output schema or provider/time budgets. Guidance is advisory data
for the provider; the deterministic category and limit filter in `enforce` is
the authoritative guard, and exact quotes do not prove truth or entailment.

The file is read once per admission. Durable work keeps the normalized
snapshot it was admitted with (`build_bundle` / `validate_capture`); a later
file change only affects new admissions. Import-light by design: hooks reach
this module through `jobs.enqueue_mine`.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import posixpath
import re
import stat
import tomllib

FORMAT = 1
BUILTIN_VERSION = 'builtin-v1'
CHANNELS = ('memories', 'lessons', 'signals', 'assertions', 'contradictions',
            'pin_suggestions', 'contradictions_with_pins', 'domain_proposals')
DOMAIN_CHANNELS = CHANNELS[:5]
DOMAINLESS_CHANNELS = CHANNELS[5:]
# Existing mining caps (mining.MAX_ITEMS_PER_KIND and parse_extraction); a
# policy can only narrow them.
HARD_CAPS = {'memories': 8, 'lessons': 8, 'signals': 8, 'assertions': 8, 'contradictions': 5,
             'pin_suggestions': 3, 'contradictions_with_pins': 5, 'domain_proposals': 3}
# The one text field per channel that max_body_chars measures.
TEXT_FIELDS = {'memories': 'body', 'lessons': 'body', 'signals': 'body', 'assertions': 'value',
               'contradictions': 'statement', 'pin_suggestions': 'body',
               'contradictions_with_pins': 'statement', 'domain_proposals': 'description'}

MAX_FILE_BYTES = 65536
MAX_RULES = 64
MAX_GUIDANCE_CHARS = 2000
MAX_EXAMPLES = 8
MAX_EXAMPLE_CHARS = 500
MAX_BODY_CHARS = 8000
MAX_SNAPSHOT_BYTES = 65536
MAX_RENDERED_CHARS = 8000
MAX_ERRORS = 20

FRAGMENT_KEYS = ('guidance', 'examples', 'categories', 'max_items_per_category', 'max_body_chars')
# Settings a policy must never carry: capabilities that stay with the code,
# the service authorization file or the provider configuration.
RESERVED = frozenset({
    'system', 'schema', 'prompt', 'provider', 'model', 'domains', 'write_domains', 'read_domains',
    'write_projects', 'read_projects', 'authorization', 'principal', 'admin', 'evidence', 'grounding',
    'pins', 'claim_kind', 'validity', 'budget', 'max_input_chars', 'max_output_tokens', 'timeout',
    'gateway', 'audit'})
_DOMAIN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


class PolicyError(ValueError):
    """Invalid policy file. Errors carry codes and locations, never values."""

    def __init__(self, errors):
        self.errors = list(errors)[:MAX_ERRORS]
        super().__init__('invalid extraction policy: ' + '; '.join(
            f"{e['code']} at {e['location']}" for e in self.errors))


class PolicySnapshotError(ValueError):
    """A durable snapshot is malformed or does not match its digest."""

    def __init__(self):
        super().__init__('policy_snapshot_invalid')


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _sha(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class Policy:
    guidance: str = ''
    examples: tuple = ()
    categories: tuple = CHANNELS
    max_items_per_category: int | None = None
    max_body_chars: int | None = None

    def normalized(self) -> dict:
        return {'guidance': self.guidance, 'examples': [dict(e) for e in self.examples],
                'categories': list(self.categories), 'max_items_per_category': self.max_items_per_category,
                'max_body_chars': self.max_body_chars}

    @property
    def digest(self) -> str:
        return 'xp1:' + _sha(self.normalized())

    def limit(self, channel: str) -> int:
        if channel not in self.categories:
            return 0
        cap = HARD_CAPS[channel]
        return cap if self.max_items_per_category is None else min(cap, self.max_items_per_category)


BUILTIN = Policy()


@dataclass(frozen=True)
class Rule:
    domain: str | None
    project: str | None
    fragment: dict

    @property
    def label(self) -> str:
        if self.domain and self.project:
            return f'exact:{self.domain}@{self.project}'
        return f'domain:{self.domain}' if self.domain else f'project:{self.project}'


@dataclass(frozen=True)
class PolicyFile:
    global_fragment: dict
    rules: tuple

    @property
    def identity(self) -> str:
        rules = sorted(({'domain': r.domain, 'project': r.project, **r.fragment} for r in self.rules),
                       key=lambda r: (r['domain'] or '', r['project'] or ''))
        return 'xf1:' + _sha({'format': FORMAT, 'global': self.global_fragment, 'rules': rules})


class _Errors(list):
    def add(self, code, location):
        if len(self) < MAX_ERRORS:
            from .secrets import strip_secrets
            # Unknown TOML keys are user input too; errors may reach terminals/logs.
            safe = strip_secrets(str(location))[0]
            safe = _CONTROL.sub('?', safe).replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
            self.append({'code': code, 'location': safe[:160]})


def _text(value, location, limit, errors):
    from .secrets import strip_secrets
    if not isinstance(value, str):
        errors.add('invalid_type', location)
        return None
    if _CONTROL.search(value):
        errors.add('invalid_value', location)
        return None
    # Whitespace runs (including newlines) collapse, so guidance cannot forge
    # prompt section headers and formatting never changes identity.
    text = ' '.join(value.split())
    if not text:
        errors.add('empty_value', location)
        return None
    if len(text) > limit:
        errors.add('too_long', location)
        return None
    if strip_secrets(text)[1]:
        errors.add('secret_in_policy', location)
        return None
    return text


def _integer(value, location, low, high, errors):
    if not isinstance(value, int) or isinstance(value, bool):
        errors.add('invalid_type', location)
        return None
    if not low <= value <= high:
        errors.add('out_of_range', location)
        return None
    return value


def _keys(table, allowed, prefix, errors):
    for key in table:
        if key in allowed:
            continue
        errors.add('reserved_setting' if key in RESERVED else 'unknown_key', f'{prefix}{key}')


def _fragment(table, prefix, errors) -> dict:
    out = {}
    if 'guidance' in table:
        text = _text(table['guidance'], prefix + 'guidance', MAX_GUIDANCE_CHARS, errors)
        if text is not None:
            out['guidance'] = text
    if 'examples' in table:
        raw = table['examples']
        if not isinstance(raw, list):
            errors.add('invalid_type', prefix + 'examples')
        elif len(raw) > MAX_EXAMPLES:
            errors.add('too_many_examples', prefix + 'examples')
        else:
            examples, seen = [], {}
            for index, item in enumerate(raw):
                where = f'{prefix}examples[{index}]'
                if not isinstance(item, dict):
                    errors.add('invalid_type', where)
                    continue
                _keys(item, ('kind', 'text'), where + '.', errors)
                if 'kind' not in item or 'text' not in item:
                    errors.add('missing_key', where)
                    continue
                kind = item['kind']
                if kind not in ('positive', 'negative'):
                    errors.add('invalid_value', where + '.kind')
                    continue
                text = _text(item['text'], where + '.text', MAX_EXAMPLE_CHARS, errors)
                if text is None:
                    continue
                if text in seen:
                    errors.add('duplicate_example' if seen[text] == kind else 'conflicting_examples', where)
                    continue
                seen[text] = kind
                examples.append({'kind': kind, 'text': text})
            out['examples'] = examples
    if 'categories' in table:
        raw = table['categories']
        if not isinstance(raw, list) or not all(isinstance(c, str) for c in raw):
            errors.add('invalid_type', prefix + 'categories')
        elif any(c not in CHANNELS for c in raw):
            errors.add('unknown_category', prefix + 'categories')
        elif len(set(raw)) != len(raw):
            errors.add('duplicate_category', prefix + 'categories')
        else:
            out['categories'] = [c for c in CHANNELS if c in raw]
    if 'max_items_per_category' in table:
        value = _integer(table['max_items_per_category'], prefix + 'max_items_per_category', 0, max(HARD_CAPS.values()), errors)
        if value is not None:
            out['max_items_per_category'] = value
    if 'max_body_chars' in table:
        value = _integer(table['max_body_chars'], prefix + 'max_body_chars', 1, MAX_BODY_CHARS, errors)
        if value is not None:
            out['max_body_chars'] = value
    return out


def _project_selector(value) -> bool:
    if not isinstance(value, str) or not value or len(value) > 4096 or '\x00' in value:
        return False
    if value in ('global', 'unknown'):
        return True
    return value.startswith('/') and posixpath.normpath(value) == value and not value.startswith('//')


def parse_document(data) -> PolicyFile:
    """Strictly validate a parsed TOML document; collect every error found."""
    errors = _Errors()
    if not isinstance(data, dict):
        raise PolicyError([{'code': 'invalid_type', 'location': 'file'}])
    version = data.get('version')
    if not isinstance(version, int) or isinstance(version, bool) or version != FORMAT:
        errors.add('unsupported_version', 'version')
    _keys(data, ('version', 'global', 'rules'), '', errors)
    global_fragment = {}
    if 'global' in data:
        if not isinstance(data['global'], dict):
            errors.add('invalid_type', 'global')
        else:
            _keys(data['global'], FRAGMENT_KEYS, 'global.', errors)
            global_fragment = _fragment(data['global'], 'global.', errors)
    rules = []
    raw_rules = data.get('rules', [])
    if not isinstance(raw_rules, list):
        errors.add('invalid_type', 'rules')
    elif len(raw_rules) > MAX_RULES:
        errors.add('too_many_rules', 'rules')
    else:
        selectors = set()
        for index, rule in enumerate(raw_rules):
            where = f'rules[{index}]'
            if not isinstance(rule, dict):
                errors.add('invalid_type', where)
                continue
            _keys(rule, FRAGMENT_KEYS + ('domain', 'project'), where + '.', errors)
            domain, project = rule.get('domain'), rule.get('project')
            valid = True
            if domain is not None and (not isinstance(domain, str) or not _DOMAIN.match(domain)):
                errors.add('invalid_selector', where + '.domain')
                valid = False
            if project is not None and not _project_selector(project):
                errors.add('invalid_selector', where + '.project')
                valid = False
            if domain is None and project is None:
                errors.add('empty_selector', where)
                valid = False
            fragment = _fragment(rule, where + '.', errors)
            if not any(key in rule for key in FRAGMENT_KEYS):
                errors.add('empty_rule', where)
                valid = False
            if valid and (domain, project) in selectors:
                errors.add('duplicate_selector', where)
                valid = False
            if valid:
                selectors.add((domain, project))
                rules.append(Rule(domain, project, fragment))
    if errors:
        raise PolicyError(errors)
    return PolicyFile(global_fragment, tuple(rules))


def load_file(path) -> PolicyFile:
    """Read one bounded regular file and validate it. Errors never echo content."""
    try:
        fd = os.open(os.fspath(path), os.O_RDONLY | getattr(os, 'O_CLOEXEC', 0))
    except (OSError, TypeError, ValueError):
        raise PolicyError([{'code': 'file_unreadable', 'location': 'file'}]) from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise PolicyError([{'code': 'file_unreadable', 'location': 'file'}])
        with os.fdopen(os.dup(fd), 'rb') as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
    except OSError:
        raise PolicyError([{'code': 'file_unreadable', 'location': 'file'}]) from None
    finally:
        os.close(fd)
    return validate_source(raw)


def validate_source(raw) -> PolicyFile:
    """The one shared validator for file text (str or bytes), e.g. a future dashboard editor."""
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    if len(raw) > MAX_FILE_BYTES:
        raise PolicyError([{'code': 'file_too_large', 'location': 'file'}])
    try:
        data = tomllib.loads(raw.decode('utf-8'))
    except UnicodeDecodeError:
        raise PolicyError([{'code': 'invalid_encoding', 'location': 'file'}]) from None
    except tomllib.TOMLDecodeError:
        raise PolicyError([{'code': 'invalid_toml', 'location': 'file'}]) from None
    return parse_document(data)


def _merge(layers) -> Policy:
    values = BUILTIN.normalized()
    for fragment in layers:
        values.update({k: (list(v) if isinstance(v, list) else v) for k, v in fragment.items()})
    return Policy(values['guidance'], tuple(values['examples']), tuple(values['categories']),
                  values['max_items_per_category'], values['max_body_chars'])


def resolve(policy_file: PolicyFile | None, domain: str, project: str):
    """Field-wise precedence: builtin, global, domain, project, exact domain+project.

    Arrays replace earlier arrays. Returns (Policy, applied scope labels).
    """
    trace, layers = ['builtin'], []
    if policy_file is None:
        return BUILTIN, trace
    if policy_file.global_fragment:
        trace.append('global')
        layers.append(policy_file.global_fragment)
    for match in (lambda r: r.domain == domain and r.project is None,
                  lambda r: r.domain is None and r.project == project,
                  lambda r: r.domain == domain and r.project == project):
        rule = next((r for r in policy_file.rules if match(r)), None)
        if rule is not None:
            trace.append(rule.label)
            layers.append(rule.fragment)
    return _merge(layers), trace


def resolve_domainless(policy_file: PolicyFile | None, project: str):
    """Domainless outputs use global then project-only rules, never a domain's rule."""
    trace, layers = ['builtin'], []
    if policy_file is None:
        return BUILTIN, trace
    if policy_file.global_fragment:
        trace.append('global')
        layers.append(policy_file.global_fragment)
    rule = next((r for r in policy_file.rules if r.domain is None and r.project == project), None)
    if rule is not None:
        trace.append(rule.label)
        layers.append(rule.fragment)
    return _merge(layers), trace


@dataclass(frozen=True)
class Bundle:
    """The normalized policies for one admitted project and its permitted domains."""
    snapshot: dict
    digest: str

    @property
    def domains(self) -> frozenset:
        return frozenset(self.snapshot['domains'])

    def policy(self, domain: str) -> Policy | None:
        key = self.snapshot['domains'].get(domain)
        return None if key is None else _from_normalized(self.snapshot['policies'][key])

    def domainless(self) -> Policy:
        return _from_normalized(self.snapshot['policies'][self.snapshot['domainless']])

    def capture(self) -> dict:
        return {'digest': self.digest, 'snapshot': self.snapshot}


def _from_normalized(values) -> Policy:
    return Policy(values['guidance'], tuple(dict(e) for e in values['examples']), tuple(values['categories']),
                  values['max_items_per_category'], values['max_body_chars'])


def canonical_project(project) -> str:
    """The project key rules match: the same canonical scope mining writes to."""
    if not project or project == 'unknown':
        return 'unknown'
    if project == 'global':
        return 'global'
    try:
        from .scope import project_id
        return project_id(project)
    except (ValueError, OSError):
        return 'unknown'


def build_bundle(policy_file: PolicyFile | None, project: str, domains) -> Bundle:
    policies, mapping = {}, {}
    for domain in sorted(set(domains)):
        effective, _ = resolve(policy_file, domain, project)
        policies[effective.digest] = effective.normalized()
        mapping[domain] = effective.digest
    domainless, _ = resolve_domainless(policy_file, project)
    policies[domainless.digest] = domainless.normalized()
    snapshot = {'format': FORMAT, 'builtin': BUILTIN_VERSION, 'project': project,
                'policies': policies, 'domains': mapping, 'domainless': domainless.digest}
    if len(canonical(snapshot).encode()) > MAX_SNAPSHOT_BYTES:
        raise PolicyError([{'code': 'bundle_too_large', 'location': 'bundle'}])
    bundle = Bundle(snapshot, 'xb1:' + _sha(snapshot))
    if len(render_preferences(bundle, mapping)) > MAX_RENDERED_CHARS:
        raise PolicyError([{'code': 'preferences_too_long', 'location': 'bundle'}])
    return bundle


def builtin_bundle(project: str, domains) -> Bundle:
    return build_bundle(None, project, domains)


def is_builtin(bundle: Bundle) -> bool:
    return all(_from_normalized(p) == BUILTIN for p in bundle.snapshot['policies'].values())


def capture(cfg, project, domains) -> dict | None:
    """Admission-time capture from the configured file; None means no custom policy.

    Raises PolicyError for an invalid file so that new admission fails visibly
    without consuming a queue cursor.
    """
    path = getattr(cfg, 'mine_policy_file', None)
    if path is None:
        return None
    return build_bundle(load_file(path), canonical_project(project), domains).capture()


def _valid_policy(values) -> bool:
    if not isinstance(values, dict) or set(values) != set(FRAGMENT_KEYS):
        return False
    errors = _Errors()
    table = {k: v for k, v in values.items() if v is not None and not (k == 'guidance' and v == '')}
    fragment = _fragment(table, '', errors)
    return not errors and _merge([fragment]).normalized() == values


def validate_capture(captured) -> Bundle:
    """Re-check a durable snapshot completely; never fall back to today's file."""
    try:
        if not isinstance(captured, dict) or set(captured) != {'digest', 'snapshot'}:
            raise PolicySnapshotError()
        snapshot, digest = captured['snapshot'], captured['digest']
        if (not isinstance(snapshot, dict) or set(snapshot) != {'format', 'builtin', 'project', 'policies', 'domains', 'domainless'}
                or snapshot['format'] != FORMAT or snapshot['builtin'] != BUILTIN_VERSION
                or not isinstance(snapshot['project'], str) or not isinstance(snapshot['policies'], dict)
                or not isinstance(snapshot['domains'], dict) or not isinstance(digest, str)
                or len(canonical(snapshot).encode()) > MAX_SNAPSHOT_BYTES):
            raise PolicySnapshotError()
        for key, values in snapshot['policies'].items():
            if not _valid_policy(values) or _from_normalized(values).digest != key:
                raise PolicySnapshotError()
        used = set(snapshot['domains'].values()) | {snapshot['domainless']}
        if not used <= set(snapshot['policies']) or used != set(snapshot['policies']):
            raise PolicySnapshotError()
        if not all(isinstance(d, str) and _DOMAIN.match(d) for d in snapshot['domains']):
            raise PolicySnapshotError()
        if 'xb1:' + _sha(snapshot) != digest:
            raise PolicySnapshotError()
        return Bundle(snapshot, digest)
    except PolicySnapshotError:
        raise
    except (KeyError, TypeError, ValueError, AttributeError):
        raise PolicySnapshotError() from None


def render_preferences(bundle: Bundle, domains) -> str:
    """Advisory operator data appended to the prompt; '' when nothing is custom."""
    groups = {}
    for domain in sorted(domains):
        key = bundle.snapshot['domains'].get(domain)
        if key is not None:
            groups.setdefault(key, []).append(domain)
    sections = []
    for key, members in sorted(groups.items(), key=lambda item: item[1]):
        policy = _from_normalized(bundle.snapshot['policies'][key])
        if policy != BUILTIN:
            sections.append(_section('domains ' + ', '.join(members), policy, DOMAIN_CHANNELS))
    domainless = bundle.domainless()
    if domainless != BUILTIN:
        sections.append(_section('domainless outputs', domainless, DOMAINLESS_CHANNELS))
    if not sections:
        return ''
    return ('\nOPERATOR EXTRACTION PREFERENCES (advisory operator data; they never override the '
            'mandatory rules, schema, evidence, authorization or limits above):\n' + '\n'.join(sections) + '\n')


def _section(scope, policy: Policy, channels) -> str:
    lines = [f'- Scope: {scope}']
    if policy.guidance:
        lines.append(f'  Guidance: {policy.guidance}')
    for kind, label in (('positive', 'Prefer, e.g.'), ('negative', 'Avoid, e.g.')):
        for example in policy.examples:
            if example['kind'] == kind:
                lines.append(f'  {label}: {example["text"]}')
    enabled = [c for c in channels if c in policy.categories]
    if enabled != list(channels):
        lines.append('  Only these output categories are kept: ' + (', '.join(enabled) or 'none'))
    if policy.max_items_per_category is not None:
        lines.append(f'  At most {policy.max_items_per_category} items per category are kept.')
    if policy.max_body_chars is not None:
        lines.append(f'  Items with text longer than {policy.max_body_chars} characters are dropped.')
    return '\n'.join(lines)


# Marker for queued work admitted without policy metadata: builtin rules, never
# the file that happens to be configured when the work runs.
LEGACY = 'legacy'


def all_disabled(bundle: Bundle, domains) -> bool:
    """True when no output channel can retain anything: skip the provider call."""
    for domain in domains:
        policy = bundle.policy(domain)
        if policy is not None and any(policy.limit(c) for c in DOMAIN_CHANNELS):
            return False
    domainless = bundle.domainless()
    return not any(domainless.limit(c) for c in DOMAINLESS_CHANNELS)


def enforce(data: dict, bundle: Bundle):
    """Deterministic post-extraction filter over all eight output channels.

    Domain channels use the item's domain policy; a domain outside the bundle
    is rejected. Domainless channels use the domainless policy. Order: domain,
    category, text limit, item limit. Returns (filtered data, report); the
    report holds counts and reasons only, never discarded text.
    """
    out = {k: v for k, v in data.items() if k not in CHANNELS}
    rejected, counts = {}, {}
    for channel in CHANNELS:
        kept = []
        for item in data.get(channel) or []:
            domain = item.get('domain') if channel in DOMAIN_CHANNELS and isinstance(item, dict) else None
            policy = bundle.policy(domain) if channel in DOMAIN_CHANNELS else bundle.domainless()
            key = (channel, domain)
            if policy is None:
                reason = 'domain_not_bound'
            elif channel not in policy.categories:
                reason = 'category_disabled'
            elif policy.max_body_chars is not None and len(str(item.get(TEXT_FIELDS[channel]) or '')) > policy.max_body_chars:
                reason = 'body_limit'
            elif counts.get(key, 0) >= policy.limit(channel):
                reason = 'item_limit'
            else:
                reason = None
            if reason:
                bucket = rejected.setdefault(channel, {})
                bucket[reason] = bucket.get(reason, 0) + 1
                continue
            counts[key] = counts.get(key, 0) + 1
            kept.append(item)
        out[channel] = kept
    return out, {'digest': bundle.digest, 'rejected': rejected}
