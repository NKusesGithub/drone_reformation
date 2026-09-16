#!/usr/bin/python3
"""Edit the swarm config on both sides at once.

Keeps these in sync:
  CrazySwarm2-with-Mocap/.../crazyflie/config/crazyflies.yaml   enabled + initial_position
  drone_reformation/config.yaml                                 drones.ids, vehicle_names, old_formation

Both repos are looked for next to this script, so it can live in the folder holding them or
inside either repo. If drone_reformation/config.yaml isn't found, only crazyflies.yaml is
edited (--formation is ignored).

Drones are given by number (12 = cf12) or by name (cf12). `set` with a number that isn't
in crazyflies.yaml yet adds it (URI ...E7<NN>, enabled); a commented-out one is uncommented.

Usage:
  ./swarm_config.py show
  ./swarm_config.py set 5 8 12 --formation 1,2        fly exactly these drones (both files)
  ./swarm_config.py set 5 8 12 --formation 1,2 --from-mocap   ...and read their positions
  ./swarm_config.py pos                               every enabled drone's position from /poses
  ./swarm_config.py pos 12                            just cf12's position from /poses
  ./swarm_config.py pos 12=-1.03,0.93,0.04            type cf12's position in
  ./swarm_config.py pos 5 8 12=-1.03,0.93,0.04        mix: 5 and 8 from /poses, 12 typed

Every write prints a diff and leaves <file>.bak; add --dry-run to only print the diff.

Edits are line-level, so comments and layout in both files survive untouched. IDs are
derived exactly as crazyflie_py does it (last URI byte read as hex: ...E712 -> 18),
because that is the number the API bridge reports and drone_reformation must use.
--from-mocap needs ROS sourced (source <ws>/install/setup.bash) and ros2 launch running.
"""

import argparse
import difflib
import math
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
# The folder holding both repos: this script's folder, its parent if it sits at a repo root,
# or its grandparent if it sits in a repo subfolder (drone_reformation/scripts/).
ROOTS = (HERE, os.path.dirname(HERE), os.path.dirname(os.path.dirname(HERE)))
CRAZYSWARM_REPO = 'CrazySwarm2-with-Mocap'
CRAZYFLIES_REL = os.path.join('src', 'crazyswarm2', 'crazyflie', 'config', 'crazyflies.yaml')
REFORMATION_REPO = 'drone_reformation'
MIN_SPACING = 1.0  # m, QUICKSTART's minimum start spacing


def die(msg):
    sys.exit(f'error: {msg}')


def warn(msg):
    print(f'warning: {msg}', file=sys.stderr)


def api_id(uri):
    """Same rule as crazyflie_py.CrazyflieServer: last two URI chars as hex."""
    return int(uri[-2:], 16)


def fmt_list(values):
    return '[' + ', '.join(str(v) for v in values) + ']'


def fmt_pos(pos):
    return '[' + ', '.join(f'{v:.4f}' for v in pos) + ']'


# --------------------------------------------------------------------------------------
# crazyflies.yaml
# --------------------------------------------------------------------------------------

class Robot:
    def __init__(self, name, start, end, commented):
        self.name = name
        self.start = start          # index of the "  cfN:" line
        self.end = end              # one past the block's last line
        self.commented = commented  # the whole block is commented out
        self.fields = {}            # field -> (line index, raw value text)

    def value(self, field):
        return self.fields[field][1] if field in self.fields else None

    @property
    def uri(self):
        return self.value('uri')

    @property
    def enabled(self):
        return not self.commented and str(self.value('enabled')).lower() == 'true'

    @property
    def position(self):
        raw = self.value('initial_position')
        try:
            return [float(v) for v in raw.strip('[]').split(',')]
        except (AttributeError, ValueError):
            return None


ROBOT_RE = re.compile(r'^  (\w+):\s*(#.*)?$')
FIELD_RE = re.compile(r'^    (\w+):\s*(.*?)\s*(#.*)?$')
C_ROBOT_RE = re.compile(r'^  #\s?(\w+):\s*$')
C_FIELD_RE = re.compile(r'^  #\s{2,}(\w+):\s*(.*?)\s*(#.*)?$')


def parse_robots(lines):
    try:
        top = lines.index('robots:\n')
    except ValueError:
        die('crazyflies.yaml has no top-level "robots:" line')
    end = next((i for i in range(top + 1, len(lines)) if re.match(r'^\S', lines[i])), len(lines))

    robots = {}
    i = top + 1
    while i < end:
        line = lines[i]
        m, cm = ROBOT_RE.match(line), C_ROBOT_RE.match(line)
        if m or cm:
            name, commented = (m or cm).group(1), bool(cm)
            field_re = C_FIELD_RE if commented else FIELD_RE
            j, fields = i + 1, {}
            while j < end and (fm := field_re.match(lines[j])):
                fields[fm.group(1)] = (j, fm.group(2))
                j += 1
            if 'uri' in fields:
                robot = Robot(name, i, j, commented)
                robot.fields = fields
                if not commented or name not in robots:  # an active entry beats a commented copy
                    robots[name] = robot
            elif not commented:
                die(f'crazyflies.yaml: "{name}" is not in the expected block format '
                    f'(line {i + 1}); edit it by hand')
            i = j
        else:
            i += 1
    return robots


def set_field(lines, robot, field, value):
    if field not in robot.fields:
        die(f'crazyflies.yaml: {robot.name} has no "{field}:" line')
    idx = robot.fields[field][0]
    m = FIELD_RE.match(lines[idx])
    comment = f'  {m.group(3)}' if m.group(3) else ''
    lines[idx] = f'    {field}: {value}{comment}\n'


def uncomment(lines, robot):
    for k in range(robot.start, robot.end):
        lines[k] = re.sub(r'^(\s*)# ?', r'\1', lines[k], count=1)


def add_robot(lines, robots, number):
    """Insert a new enabled cfN entry, in number order, modelled on the existing ones.

    URI follows the lab's pattern (cf5 -> ...E705, cf12 -> ...E712): same radio/channel/
    datarate/prefix as the other drones, name number as the last two digits.
    """
    if number > 99:
        die(f'cf{number}: the address pattern only has two digits; add it by hand')
    active = [r for r in robots.values() if not r.commented] or list(robots.values())
    if not active:
        die('crazyflies.yaml has no drone entries to copy the URI/type from; add it by hand')
    uri = active[0].uri[:-2] + f'{number:02d}'
    types = [r.value('type').split('#')[0].strip() for r in active if r.value('type')]
    rtype = max(set(types), key=types.count) if types else 'cf21'

    block = [f'  cf{number}:\n',
             '    enabled: true\n',
             f'    uri: {uri}\n',
             '    initial_position: [0.0000, 0.0000, 0.0000]\n',
             f'    type: {rtype}  # see robot_types\n',
             '\n']
    later = sorted((r.start for r in robots.values()
                    if int(re.sub(r'\D', '', r.name) or 0) > number))
    if later:
        at = later[0]
    else:                                   # end of the robots: block, before its trailing blank
        top = lines.index('robots:\n')
        at = next((i for i in range(top + 1, len(lines)) if re.match(r'^\S', lines[i])),
                  len(lines))
        if lines[at - 1].strip() != '':
            block.insert(0, '\n')
    lines[at:at] = block
    print(f'added cf{number}: uri {uri}, type {rtype}')
    if api_id(uri) != number:
        warn(f'cf{number} will have bridge id {api_id(uri)} (the URI byte is read as hex)')
    return uri


# --------------------------------------------------------------------------------------
# drone_reformation config.yaml
# --------------------------------------------------------------------------------------

def find_key(lines, section, key):
    """Index of the active "  key:" line inside top-level "section:"."""
    try:
        top = lines.index(f'{section}:\n')
    except ValueError:
        die(f'config.yaml has no top-level "{section}:" line')
    for i in range(top + 1, len(lines)):
        if re.match(r'^\S', lines[i]):
            break
        if re.match(rf'^  {key}:', lines[i]):
            return i
    return None


def read_flow_list(line):
    m = re.search(r'\[(.*?)\]', line)
    if not m:
        return None
    return [int(v) for v in m.group(1).split(',') if v.strip()]


def read_reformation(lines):
    ids_i = find_key(lines, 'drones', 'ids')
    form_i = find_key(lines, 'mission', 'old_formation')
    return (read_flow_list(lines[ids_i]) if ids_i is not None else None,
            read_flow_list(lines[form_i]) if form_i is not None else None)


def write_reformation(lines, selected, formation):
    ids = [api_id(r.uri) for r in selected]

    i = find_key(lines, 'drones', 'ids')
    if i is None:
        die('config.yaml: no active "ids:" line under drones:')
    comment = re.search(r'\s#.*$', lines[i].rstrip('\n'))
    lines[i] = f'  ids: {fmt_list(ids)}{comment.group(0) if comment else ""}\n'

    v = find_key(lines, 'drones', 'vehicle_names')
    if v is None:
        die('config.yaml: no "vehicle_names:" under drones:')
    end = v + 1
    while end < len(lines) and (lines[end].strip() == '' or lines[end].startswith('    ')):
        end += 1
    while end > v + 1 and lines[end - 1].strip() == '':
        end -= 1                                   # keep trailing blank lines outside
    kept = [l for l in lines[v + 1:end] if l.lstrip().startswith('#')]  # commented-out entries
    active = [f'    "{api_id(r.uri)}": {r.name}\n' for r in selected]
    lines[v + 1:end] = kept + active

    if formation is not None:
        f = find_key(lines, 'mission', 'old_formation')
        if f is None:
            die('config.yaml: no active "old_formation:" line under mission:')
        lines[f] = f'  old_formation: {fmt_list(formation)}\n'  # old trailing comment would be stale


# --------------------------------------------------------------------------------------
# positions
# --------------------------------------------------------------------------------------

def known(robots):
    nums = lambda cond: ' '.join(sorted((re.sub(r'\D', '', n) or n for n, r in robots.items()
                                         if cond(r)), key=lambda x: (len(x), x)))
    return (f'enabled: {nums(lambda r: r.enabled) or "-"}, '
            f'disabled: {nums(lambda r: not r.enabled and not r.commented) or "-"}, '
            f'commented out: {nums(lambda r: r.commented) or "-"}')


def resolve(token, robots, allow_new=False):
    """'12' or 'cf12' -> 'cf12'. A number matches the number in a drone's name.
    With allow_new, an unknown number returns None (caller adds the drone)."""
    if token in robots:
        return token
    if token.isdigit():
        matches = [n for n in robots if re.sub(r'\D', '', n) == str(int(token))]
        if len(matches) == 1:
            return matches[0]
        if matches:
            die(f'drone {token} is ambiguous: {matches}. Use the name')
        bridge = [n for n, r in robots.items() if api_id(r.uri) == int(token)]
        if allow_new and not bridge:
            return None
        hint = (f'\n  ({token} is the bridge id of {bridge[0]}; use the number in its name: '
                f'{re.sub(r"[^0-9]", "", bridge[0])})') if bridge else ''
        die(f'no drone {token} in crazyflies.yaml ({known(robots)}){hint}')
    die(f'no drone "{token}" in crazyflies.yaml ({known(robots)})')


def split_pos_items(items, robots):
    """['5', '12=-1,0.9,0.04'] -> typed {cf12: [...]}, bare [cf5] (bare = read from mocap)."""
    typed, bare = {}, []
    for item in items or []:
        key, eq, val = item.partition('=')
        name = resolve(key, robots)
        if name in typed or name in bare:
            die(f'{name} is given twice')
        if not eq:
            bare.append(name)
            continue
        parts = val.split(',')
        try:
            if len(parts) != 3:
                raise ValueError
            typed[name] = [float(v) for v in parts]
        except ValueError:
            die(f'bad position "{item}", expected ID=x,y,z  e.g. 12=-1.03,0.93,0.04')
    return typed, bare


def positions_from_mocap(names, topic, samples, timeout):
    try:
        import rclpy
        from rclpy.qos import qos_profile_sensor_data
        from motion_capture_tracking_interfaces.msg import NamedPoseArray
    except ImportError as exc:
        die(f'--from-mocap needs ROS 2: {exc}\n'
            '  run with /usr/bin/python3 after: source ~/S_ENG/CrazySwarm2-with-Mocap/install/setup.bash')

    wanted = set(names)
    frames, seen = [], set()

    def on_poses(msg):
        by_name = {p.name: p.pose.position for p in msg.poses}
        seen.update(by_name)
        if wanted <= by_name.keys():
            frames.append({n: (by_name[n].x, by_name[n].y, by_name[n].z) for n in wanted})

    rclpy.init()
    node = rclpy.create_node('swarm_config_mocap')
    node.create_subscription(NamedPoseArray, topic, on_poses, qos_profile_sensor_data)
    print(f'reading {topic} ({samples} frames, up to {timeout:.0f} s)...')
    deadline = time.monotonic() + timeout
    while len(frames) < samples and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
    node.destroy_node()
    rclpy.shutdown()

    if not frames:
        if not seen:
            die(f'no messages on {topic} in {timeout:.0f} s. Is ros2 launch running with mocap? '
                '(ros2 topic hz /poses)')
        die(f'Motive never sent all of {sorted(wanted)} in one frame.\n'
            f'  missing: {sorted(wanted - seen)}\n'
            f'  Motive is sending: {sorted(seen)}\n'
            '  Rigid-body names in Motive must equal the crazyflies.yaml names.')

    result = {}
    for n in names:
        pts = [f[n] for f in frames]
        mean = [sum(p[k] for p in pts) / len(pts) for k in range(3)]
        spread = max(math.dist(p, mean) for p in pts)
        if spread > 0.02:
            warn(f'{n} moved {spread * 100:.1f} cm while sampling. Is it sitting still?')
        result[n] = mean
    if len(frames) < samples:
        warn(f'only got {len(frames)} of {samples} frames; averaged what arrived')
    return result


def check_spacing(positions):
    names = sorted(positions)
    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            d = math.dist(positions[names[a]][:2], positions[names[b]][:2])
            if d < MIN_SPACING:
                warn(f'{names[a]} and {names[b]} start {d:.2f} m apart (< {MIN_SPACING} m)')


# --------------------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------------------

def load(path):
    if not os.path.exists(path):
        die(f'not found: {path}')
    with open(path) as f:
        return f.readlines()


def commit(path, old, new, dry_run):
    diff = list(difflib.unified_diff(old, new, f'{path} (before)', f'{path} (after)'))
    if not diff:
        print(f'{path}: no change')
        return
    sys.stdout.writelines(diff)
    if dry_run:
        return
    with open(path + '.bak', 'w') as f:
        f.writelines(old)
    with open(path, 'w') as f:
        f.writelines(new)
    print(f'wrote {path}  (backup: {os.path.basename(path)}.bak)')


def validate(cf_lines, rf_lines, selected, formation):
    """Parse the edited text as YAML and check it says what we meant. Skipped without PyYAML."""
    try:
        import yaml
    except ImportError:
        print('(PyYAML not available: skipped YAML check)')
        return
    try:
        cf = yaml.safe_load(''.join(cf_lines))
        rf = yaml.safe_load(''.join(rf_lines)) if rf_lines is not None else None
    except yaml.YAMLError as exc:
        die(f'edit produced invalid YAML, nothing written:\n{exc}')
    checks = [
        (sorted(n for n, r in cf['robots'].items() if r.get('enabled')),
         sorted(r.name for r in selected), 'crazyflies.yaml enabled drones'),
    ]
    if rf is not None:
        checks += [
            (rf['drones']['ids'], [api_id(r.uri) for r in selected], 'config.yaml drones.ids'),
            ({int(k): v for k, v in rf['drones']['vehicle_names'].items()},
             {api_id(r.uri): r.name for r in selected}, 'config.yaml vehicle_names'),
        ]
        if formation is not None:
            checks.append((rf['mission']['old_formation'], formation, 'config.yaml old_formation'))
    for got, want, what in checks:
        if got != want:
            die(f'internal check failed, nothing written: {what} = {got}, expected {want}')
    print('YAML check passed')


def report_problems(robots, ref_ids, formation):
    problems = []
    enabled = [r for r in robots.values() if r.enabled]
    ids = [api_id(r.uri) for r in enabled]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        problems.append(f'two enabled drones share API id {sorted(dupes)}: fix their URIs')
    if ref_ids is not None and sorted(ref_ids) != sorted(ids):
        problems.append(f'drone_reformation ids {ref_ids} != enabled drones {sorted(ids)} '
                        f'(fix: ./swarm_config.py set {" ".join(r.name for r in enabled)})')
    if formation is not None and sum(formation) != len(enabled):
        problems.append(f'old_formation {formation} has {sum(formation)} slots for '
                        f'{len(enabled)} drones (fix: --formation)')
    return problems


def cmd_show(args):
    robots = parse_robots(load(args.crazyflies))
    ref_ids = formation = None
    if args.reformation:
        ref_ids, formation = read_reformation(load(args.reformation))

    ref_label = args.reformation or f'(skipped: {args.reformation_missing})'
    print(f'crazyflies.yaml  {args.crazyflies}')
    print(f'config.yaml      {ref_label}\n')
    print(f'{"name":<6} {"state":<10} {"uri":<32} {"api id":<7} initial_position')
    order = sorted(robots.values(), key=lambda r: (not r.enabled, r.commented, api_id(r.uri)))
    for r in order:
        state = 'commented' if r.commented else ('enabled' if r.enabled else 'disabled')
        rid = api_id(r.uri)
        note = f'{rid}*' if str(rid) != re.sub(r'\D', '', r.name) else str(rid)
        print(f'{r.name:<6} {state:<10} {r.uri:<32} {note:<7} {r.value("initial_position")}')
    if any(str(api_id(r.uri)) != re.sub(r'\D', '', r.name) for r in robots.values()):
        print('\n* API id differs from the number in the name (URI byte is hex)')
    if args.reformation:
        print(f'\ndrone_reformation: ids {ref_ids}   old_formation {formation}')

    problems = report_problems(robots, ref_ids, formation)
    for p in problems:
        print(f'PROBLEM: {p}')
    if not problems:
        print('both sides agree' if args.reformation
              else '\ncrazyflies.yaml OK (drone_reformation not checked)')


def cmd_set(args):
    cf_old = load(args.crazyflies)
    cf_new = list(cf_old)
    robots = parse_robots(cf_new)

    names = [resolve(t, robots, allow_new=True) or f'cf{int(t)}' for t in args.drones]
    if len(set(names)) != len(names):
        die('a drone is listed twice')
    missing = [n for n in names if n not in robots]
    for n in missing:
        add_robot(cf_new, robots, int(n[2:]))
        robots = parse_robots(cf_new)
    if missing:
        print(f'  -> the URI must match the address stored on the drone '
              f'(cfclient: Connect -> Configure 2.x), and Motive needs a rigid body named the same')

    for r in robots.values():
        if r.commented and r.name in names:
            uncomment(cf_new, r)
            print(f'uncommented {r.name}')

    robots = parse_robots(cf_new)          # re-read now that blocks may be uncommented
    for r in robots.values():
        if r.commented:
            continue
        want = 'true' if r.name in names else 'false'
        if str(r.value('enabled')).lower() != want:
            set_field(cf_new, r, 'enabled', want)
    selected = sorted((robots[n] for n in names), key=lambda r: api_id(r.uri))
    ids = [api_id(r.uri) for r in selected]
    if len(set(ids)) != len(ids):
        die(f'selected drones share an API id: {ids}. Fix their URIs first')

    # drone_reformation first, so a formation mismatch fails before any wait on mocap.
    rf_old = rf_new = formation = None
    if args.reformation:
        rf_old = load(args.reformation)
        rf_new = list(rf_old)
        formation = [int(v) for v in args.formation.split(',')] if args.formation else None
        current_form = read_reformation(rf_old)[1]
        effective = formation if formation is not None else current_form
        if effective is not None and sum(effective) != len(selected):
            die(f'old_formation {effective} has {sum(effective)} slots but you selected '
                f'{len(selected)} drones. Pass --formation, e.g. --formation '
                + {1: '1', 2: '1,1', 3: '1,2', 4: '1,2,1', 5: '1,2,2', 6: '1,2,3'}
                .get(len(selected), ','.join(['1'] * len(selected))))
        write_reformation(rf_new, selected, formation)
    else:
        warn(f'{args.reformation_missing}: only crazyflies.yaml is changed')
        if args.formation:
            warn('--formation ignored: old_formation lives in drone_reformation/config.yaml')

    positions = gather_positions(args, robots, [r.name for r in selected], args.pos,
                                 mocap_all=args.from_mocap)
    apply_positions(cf_new, robots, positions)
    for n in missing:
        if n not in positions:
            warn(f'{n} has a placeholder initial_position [0, 0, 0]. Set it before flying: '
                 f'./swarm_config.py pos {n[2:]}   (or pos {n[2:]}=x,y,z)')

    validate(cf_new, rf_new, selected, formation)   # before anything touches disk
    commit(args.crazyflies, cf_old, cf_new, args.dry_run)
    if rf_old is not None:
        commit(args.reformation, rf_old, rf_new, args.dry_run)
    if not args.dry_run:
        print_restart()


def cmd_pos(args):
    cf_old = load(args.crazyflies)
    cf_new = list(cf_old)
    robots = parse_robots(cf_new)
    enabled = sorted(n for n, r in robots.items() if r.enabled)
    # No drones listed = every enabled drone from /poses.
    positions = gather_positions(args, robots, enabled, args.pos,
                                 mocap_all=args.from_mocap or not args.pos)
    apply_positions(cf_new, robots, positions)
    commit(args.crazyflies, cf_old, cf_new, args.dry_run)
    if not args.dry_run:
        print_restart()


def gather_positions(args, robots, enabled_names, items, mocap_all):
    """Typed ID=x,y,z wins; bare IDs are read from mocap; mocap_all reads every other one."""
    typed, bare = split_pos_items(items, robots)
    off = [n for n in [*typed, *bare] if n not in enabled_names]
    if off:
        die(f'not enabled, so no position to set: {off}. Enable first with: set ...')
    mocap = bare or ([n for n in enabled_names if n not in typed] if mocap_all else [])

    positions = dict(typed)
    if mocap:
        positions.update(positions_from_mocap(mocap, args.topic, args.samples, args.timeout))
    if positions:                          # spacing check includes the drones we're not moving
        others = {n: robots[n].position for n in enabled_names
                  if n not in positions and robots[n].position}
        check_spacing({**others, **positions})
    return positions


def apply_positions(lines, robots, positions):
    for name, pos in positions.items():
        set_field(lines, robots[name], 'initial_position', fmt_pos(pos))


def print_restart():
    print('\nConfig is read at startup: restart ros2 launch, the API bridge (uvicorn) '
          'and the stack (./scripts/startup_all.sh).')


def find_in_roots(repo, rel):
    for root in ROOTS:
        path = os.path.join(root, repo, rel)
        if os.path.exists(path):
            return path
    return None


def resolve_paths(args):
    """Fill in --crazyflies/--reformation from the repos next to this script.

    A missing crazyflies.yaml is fatal. A missing drone_reformation config leaves
    args.reformation None (that side is skipped) unless --reformation was given explicitly.
    """
    args.reformation_missing = None
    if args.crazyflies is None:
        args.crazyflies = find_in_roots(CRAZYSWARM_REPO, CRAZYFLIES_REL)
        if args.crazyflies is None:
            die(f'{os.path.join(CRAZYSWARM_REPO, CRAZYFLIES_REL)} not found under '
                f'{" or ".join(ROOTS)}. Pass --crazyflies <path>')
    if args.reformation is None:
        args.reformation = find_in_roots(REFORMATION_REPO, 'config.yaml')
        if args.reformation is None:
            repo = next((os.path.join(r, REFORMATION_REPO) for r in ROOTS
                         if os.path.isdir(os.path.join(r, REFORMATION_REPO))), None)
            args.reformation_missing = (
                f'{repo} has no config.yaml (cp config.example.yaml config.yaml)' if repo
                else f'{REFORMATION_REPO} not found under {" or ".join(ROOTS)}')
    elif not os.path.exists(args.reformation):
        die(f'not found: {args.reformation}')


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__.split('\n\n', 1)[1])
    p.add_argument('--crazyflies',
                   help='path to crazyflies.yaml (default: found next to this script)')
    p.add_argument('--reformation',
                   help='path to drone_reformation config.yaml '
                        '(default: found next to this script, skipped if absent)')
    sub = p.add_subparsers(dest='cmd', required=True)

    sub.add_parser('show', help='print both configs side by side and flag mismatches')

    def pos_opts(sp):
        sp.add_argument('--from-mocap', action='store_true',
                        help='read initial_position from /poses for every drone not typed in')
        sp.add_argument('--topic', default='/poses', help='mocap topic (default /poses)')
        sp.add_argument('--samples', type=int, default=20, help='frames to average')
        sp.add_argument('--timeout', type=float, default=5.0, help='seconds to wait for mocap')
        sp.add_argument('--dry-run', action='store_true', help='print the diff, write nothing')

    s = sub.add_parser('set', help='fly exactly these drones: updates both files')
    s.add_argument('drones', nargs='+', help='drone numbers or names, e.g. 5 8 12')
    s.add_argument('--formation', help='old_formation row widths, e.g. 1,2')
    s.add_argument('--pos', nargs='+', metavar='ID=X,Y,Z',
                   help='typed initial positions (a bare ID reads that one from /poses)')
    pos_opts(s)

    ps = sub.add_parser('pos', help='update initial_position only (default: all from /poses)')
    ps.add_argument('pos', nargs='*', metavar='ID[=X,Y,Z]',
                    help='ID reads it from /poses, ID=x,y,z types it in; none = all enabled')
    pos_opts(ps)

    args = p.parse_args()
    resolve_paths(args)
    {'show': cmd_show, 'set': cmd_set, 'pos': cmd_pos}[args.cmd](args)


if __name__ == '__main__':
    main()

