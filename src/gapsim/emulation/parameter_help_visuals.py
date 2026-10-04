"""Native animated trench shapes and spatial mechanism illustrations."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from . import trench_depo as engine
from .parameter_help_response import growth_response, ion_response
from .parameter_help_trench import TRENCH

COLORS = ('#008694', '#6c58b5', '#db790c')


def path(points, transform, close=False):
    result = QPainterPath()
    if not points:
        return result
    result.moveTo(transform(*points[0]))
    for point in points[1:]:
        result.lineTo(transform(*point))
    if close:
        result.closeSubpath()
    return result


def fit_transform(bounds, rect):
    """One common isotropic scale; never stretch one profile to fake a change."""
    xmin, ymin, xmax, ymax = bounds
    scale = min(rect.width()/max(xmax-xmin, 1.), rect.height()/max(ymax-ymin, 1.))
    cx, cy = (xmin+xmax)/2, (ymin+ymax)/2
    return lambda x, y: QPointF(rect.center().x()+(x-cx)*scale,
                               rect.center().y()-(y-cy)*scale), scale


def solid_path(frame, transform, bottom):
    profile = frame['profile']
    if not profile:
        return QPainterPath()
    result = path(profile+[(profile[-1][0], bottom), (profile[0][0], bottom)], transform, True)
    result.setFillRule(Qt.OddEvenFill)
    for loop in frame.get('voids', []):
        result.addPath(path(loop, transform, True))
    return result


def frame_at(run, progress):
    frames = run['frames']
    return frames[min(len(frames)-1, int(max(0., progress)*(len(frames)-1)+1e-9))]


def incoming_paths(points, sigma, rays):
    """Display a bounded subset of straight paths, stopping at the first wall."""
    count = min(15, int(rays))
    result = []
    top = max(y for _, y in points)+220.
    for i in range(count):
        angle = math.radians(-2*sigma+4*sigma*i/max(1, count-1))
        direction = (-math.sin(angle), -math.cos(angle))
        # Do not correlate launch x with angle: that falsely looks like a lens
        # focusing the ion population onto one interior point.
        origin = ((-300., -150., 0., 150., 300.)[(i*3) % 5], top)
        hits = [hit for a, b in zip(points, points[1:])
                if (hit := engine._model6_ray_segment_intersection(origin, direction, a, b))]
        if hits:
            distance = min(hit[0] for hit in hits)
            result.append((origin, (origin[0]+direction[0]*distance,
                                    origin[1]+direction[1]*distance)))
    return result


class TrenchAnimation(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(340)
        self.phase = 0.
        self.kind = 'display'
        self.key = ''
        self.movie = None
        self.view = 'auto'
        self.recorded_result = None
        self.recorded_bounds = None
        self.fields = []
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.advance)
        self.setAccessibleName('실제 트랜치 단면 단일 변수 비교, 변화 확대, 공간적 물리 의미')

    def configure(self, movie, key, kind, result=None):
        self.movie, self.key, self.kind = movie, key, kind
        self.recorded_result = result
        self.recorded_bounds = None
        if kind == 'frames' and result is not None and result.frame_profiles:
            self.recorded_bounds = (
                min(x for profile in result.frame_profiles for x,y in profile),
                min(y for profile in result.frame_profiles for x,y in profile)-30,
                max(x for profile in result.frame_profiles for x,y in profile),
                max(y for profile in result.frame_profiles for x,y in profile)+30)
        self.phase = 0.
        self.fields = []
        if movie:
            all_points = [p for run in movie['runs'] for f in run['frames'] for p in f['profile']]
            self.bounds = (min(x for x, y in all_points)-30., min(y for x, y in all_points)-60.,
                           max(x for x, y in all_points)+30., max(y for x, y in all_points)+90.)
            for run in movie['runs']:
                c = engine.TrenchDepoConfig(**run['config'])
                points = engine.equal_arc_resample(c.points, 20.)
                normals = engine.vertex_air_normals(points)
                self.fields.append(dict(points=points, normals=normals,
                    growth=growth_response(points, c) if getattr(c, 'recipe_model', 'legacy_calibrated_v1') == 'legacy_calibrated_v1' else [],
                    ion=ion_response(points, c),
                    rays=incoming_paths(c.points, c.redepo_incident_sigma_deg, c.redepo_incident_ray_count)))
        self.update()

    def set_view(self, view):
        self.view = view
        self.phase = 0.
        self.update()

    def advance(self):
        self.phase = (self.phase+.00625) % 1.
        self.update()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def stage(self):
        if self.view != 'auto':
            return self.view
        if self.phase < .5:
            return 'shape'
        if self.phase < .75:
            return 'zoom'
        return 'meaning'

    def progress(self):
        if self.view == 'auto':
            return min(1., self.phase/.36)
        return min(1., self.phase/.65)

    def label(self, p, text, y, color='#334155', size=None):
        p.save()
        if size:
            font = p.font(); font.setPixelSize(size); p.setFont(font)
        p.setPen(QColor(color))
        p.drawText(QRectF(10, y, 500, 23), Qt.AlignLeft | Qt.AlignVCenter, text)
        p.restore()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor('#f1f6fa'))
        p.scale(self.width()/520, self.height()/340)
        font = p.font(); font.setPixelSize(12); p.setFont(font)
        if self.movie:
            {'shape': self.draw_shapes, 'zoom': self.draw_zoom, 'meaning': self.draw_meaning}[self.stage()](p)
        else:
            self.draw_setting(p)
        p.end()

    def draw_profile(self, p, run, frame, rect, bounds, color, fill=True, initial=True):
        transform, scale = fit_transform(bounds, rect)
        p.save(); p.setClipRect(rect)
        if fill:
            current = solid_path(frame, transform, bounds[1]-2000)
            substrate = solid_path({'profile': run['config']['points']}, transform, bounds[1]-2000)
            p.setPen(Qt.NoPen); p.setBrush(QColor('#dce3e9')); p.drawPath(current)
            film = QColor(color); film.setAlpha(80)
            p.setBrush(film); p.drawPath(current.subtracted(substrate))
        if initial:
            p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor('#94a3b8'), 1, Qt.DashLine))
            p.drawPath(path(run['config']['points'], transform))
        p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor(color), 2))
        p.drawPath(path(frame['profile'], transform))
        for loop in frame['voids']:
            p.drawPath(path(loop, transform, True))
        p.restore()
        return transform, scale

    def draw_shapes(self, p):
        count = len(self.movie['runs'])
        self.label(p, f'예시 트랜치 실제 계산 · {count}조건 같은 축척·같은 진행률', 0, size=13)
        width = (504 - (count-1)*8)/count
        for i, run in enumerate(self.movie['runs']):
            rect = QRectF(8+i*(width+8), 62, width, 232)
            p.setPen(QPen(QColor('#d6e1e8'), 1)); p.setBrush(QColor('#ffffff')); p.drawRoundedRect(rect, 7, 7)
            frame = frame_at(run, self.progress())
            p.setPen(QColor(COLORS[i]))
            role = '기준 · ' if count == 3 and i == 1 else ''
            p.drawText(QRectF(rect.x(), 27, width, 22), Qt.AlignCenter, role+self.movie['labels'][i])
            c = run['config']
            progress = (f"{frame['time_s']:g} / {c['cvd_duration_s']:g} s"
                        if c.get('process_type') == 'cvd' and frame.get('time_s') is not None
                        else f"{frame['step']} / {c['cycles']} cycle")
            p.drawText(QRectF(rect.x(), 47, width, 18), Qt.AlignCenter, progress)
            transform, scale = self.draw_profile(p, run, frame, rect.adjusted(6, 10, -6, -10), self.bounds, COLORS[i])
            p.setPen(QPen(QColor('#475569'), 1))
            p.drawLine(QPointF(rect.x()+12, 280), QPointF(rect.x()+12+100*scale, 280))
            p.drawText(QPointF(rect.x()+12, 275), '100 Å')
        self.label(p, '색 영역: 추가된 막 · 회색 점선: 초기 단면 · 흰 내부: 빈 공간', 294)
        d = self.movie['difference_a']
        self.label(p, f'최종 경계 표본 차이 {d:.2f} Å · '+('차이가 작아 확대/원리로 확인' if d < 15 else '다음: 차이가 큰 위치 확대'), 316, '#87530d')

    def zoom_bounds(self):
        x, y = self.movie['focus']
        if self.movie['difference_a'] < .01:
            x, y = -210., -100.
        half = max(45., min(260., self.movie['difference_a']*2+35))
        return x-half, y-half, x+half, y+half

    def draw_zoom(self, p):
        self.label(p, '동일 위치 확대 · 조건 겹침 · X/Y 같은 확대 비율', 0, size=13)
        count = len(self.movie['runs'])
        for i, label in enumerate(self.movie['labels']):
            p.setPen(QColor(COLORS[i]))
            p.drawText(QRectF(10+i*500/count, 24, 500/count, 23), Qt.AlignCenter, label)
        rect, bounds = QRectF(16, 55, 488, 242), self.zoom_bounds()
        p.setPen(Qt.NoPen); p.setBrush(QColor('#ffffff')); p.drawRect(rect)
        for i, run in enumerate(self.movie['runs']):
            frame = run['frames'][-1]
            transform, scale = self.draw_profile(p, run, frame, rect, bounds, COLORS[i], fill=False, initial=i==0)
            # Moving marker stays on a calculated boundary, never bends it.
            visible = [pt for pt in frame['profile']+sum(frame['voids'], [])
                       if bounds[0] <= pt[0] <= bounds[2] and bounds[1] <= pt[1] <= bounds[3]]
            if visible:
                pt = visible[min(len(visible)-1, int((self.phase*3 % 1)*len(visible)))]
                p.setPen(Qt.NoPen); p.setBrush(QColor(COLORS[i])); p.drawEllipse(transform(*pt), 3, 3)
        p.setPen(QPen(QColor('#475569'), 1))
        length = min(50., (bounds[2]-bounds[0])/4)
        p.drawLine(QPointF(30, 280), QPointF(30+length*scale, 280))
        self.label(p, f'{length:g} Å 눈금 · 경계선은 계산 좌표 그대로 (임의 변형 없음)', 298)
        self.label(p, '차이가 거의 없으면 두 선이 겹칩니다. 물리 의미 그림도 함께 보세요.', 318, '#64748b')

    @staticmethod
    def moving_dot(p, start, end, fraction, color, radius=3.):
        p.setPen(Qt.NoPen); p.setBrush(QColor(color))
        point = start+(end-start)*fraction
        p.drawEllipse(point, radius, radius)

    def draw_meaning(self, p):
        family = self.movie['family']
        phase = self.phase*4 % 1 if self.view == 'auto' else self.phase
        count = len(self.movie['runs'])
        sample = min(count-1, int(phase*count))
        travel = (phase*count) % 1
        run = self.movie['runs'][sample]
        frame = run['frames'][-1]
        fields = self.fields[sample]
        self.label(p, '물리 의미 · '+self.movie['labels'][sample]+' 조건', 0, size=13)
        rect = QRectF(16, 40, 488, 248)
        bounds = (self.bounds[0], self.bounds[1], self.bounds[2], max(self.bounds[3], 250.))
        if family == 'reference':
            configs=[r['config'] for r in self.movie['runs']]
            bounds=(min(bounds[0],-max(c['deposition_feature_width_a'] for c in configs)/2-60),
                    min(bounds[1],-max(c['deposition_feature_depth_a'] for c in configs)-60),
                    max(bounds[2],max(c['deposition_feature_width_a'] for c in configs)/2+60),bounds[3])
        initial_fields = family in ('ions','growth','inhibition','depletion','transmission','reference')
        background = run['frames'][0] if initial_fields else frame
        transform, scale = self.draw_profile(p, run, background, rect, bounds, COLORS[sample])
        p.save(); p.setClipRect(rect)
        if family == 'physical_growth':
            points = frame['profile']
            if points:
                pt = points[min(len(points)-1, int(travel*len(points)))]
                p.setPen(Qt.NoPen); p.setBrush(QColor(COLORS[sample])); p.drawEllipse(transform(*pt), 4, 4)
            caption = '선택한 성장 모델로 계산한 경계 · 점은 경계 위치 표시'
            detail = '표면 이동을 임의로 과장하지 않습니다. 단면 비교/확대에서 차이를 확인하세요.'
        elif family == 'redepo':
            lines = sorted(frame['transport'], key=lambda line: line[-1], reverse=True)[:10]
            for i, (x1, y1, x2, y2, weight) in enumerate(lines):
                a, b = transform(x1, y1), transform(x2, y2)
                p.setPen(QPen(QColor('#b87b44'), 1, Qt.DashLine)); p.drawLine(a, b)
                self.moving_dot(p, a, b, (travel+i*.11) % 1, '#a95713')
            max_mass = max((v for r in self.movie['runs'] for x, y, v in r['frames'][-1]['redepo']), default=1.)
            for x, y, value in frame['redepo'][::2]:
                p.setPen(Qt.NoPen); p.setBrush(QColor('#dd5555'))
                p.drawEllipse(transform(x, y), 1+3*value/max(max_mass, 1e-12), 1+3*value/max(max_mass, 1e-12))
            caption = '점선/이동 점: 계산된 원료 경로 · 빨강: 실제 재부착 분포'
            detail = '원료 이동은 직전 Step 경로입니다. 입자 크기·속도는 설명용입니다.' if lines else '이 조건의 마지막 Step에는 유효한 원료 이동 경로가 없습니다.'
        elif family == 'ions':
            # Paths terminate at actual polygon intersections, not through walls.
            for i, (start, end) in enumerate(fields['rays']):
                a, b = transform(*start), transform(*end)
                p.setPen(QPen(QColor('#a4c4e3'), 1)); p.drawLine(a, b)
                self.moving_dot(p, a, b, (travel+i*.13) % 1, '#367fbc', 2.5)
            caption = '입사 방향과 먼저 만나는 표면 · 가려진 벽을 통과하지 않음'
            detail = '일부 방향만 그린 경로 예시입니다. 방향 수가 이온 총량은 아닙니다.'
        elif family == 'etch':
            max_field = max((v for r in self.movie['runs'] for x, y, v in r['frames'][-1]['etch']), default=1.)
            for i, (x, y, value) in enumerate(frame['etch'][::2]):
                radius = 1+5*value/max(max_field, 1e-12)
                color = QColor('#368bd2'); color.setAlpha(int(90+120*(1-travel)))
                p.setPen(Qt.NoPen); p.setBrush(color); p.drawEllipse(transform(x, y), radius, radius)
            caption = '파랑 원: 엔진이 계산한 제거 위치와 상대 제거량'
            detail = '모든 조건에 같은 원 크기 기준을 씁니다. 원의 크기는 실제 구멍 크기가 아닙니다.'
        elif family == 'mesh':
            for i, pt in enumerate(frame['profile']):
                p.setPen(Qt.NoPen); p.setBrush(QColor(COLORS[sample])); p.drawEllipse(transform(*pt), 2., 2.)
            caption = f"표면을 나눈 실제 계산점: {len(frame['profile'])}개"
            detail = '촘촘함은 계산 해상도입니다. 물리적인 원자 수나 증착량이 아닙니다.'
        elif family == 'reference':
            c = run['config']; width = c['deposition_feature_width_a']; depth = c['deposition_feature_depth_a']
            p.setPen(QPen(QColor('#9867c0'), 2, Qt.DashLine))
            p.drawLine(transform(-width/2, 80), transform(width/2, 80))
            p.drawLine(transform(360, 0), transform(360, -depth))
            caption = f"보라 선: 계산용 기준 폭 {width:g} Å · 깊이 {depth:g} Å"
            detail = '기준 치수는 모델 계산에 쓰이며 초기 구조 좌표를 늘리거나 줄이지 않습니다.'
        elif family == 'closure':
            for loop in frame['voids']:
                if loop:
                    pt = loop[min(len(loop)-1, int(travel*len(loop)))]
                    p.setPen(Qt.NoPen); p.setBrush(QColor('#dd5555')); p.drawEllipse(transform(*pt), 4, 4)
            caption = '흰 영역: 계산에 남아 있는 폐공간 · 경계 이동: 잔류 채움'
            detail = '전체 예산 안에서 채웁니다. 감쇠 길이는 후보 채움 총량의 공간 가중치입니다.'
        elif family == 'smoothing':
            for pt in frame['profile'][::4]:
                p.setPen(Qt.NoPen); p.setBrush(QColor('#657b92')); p.drawEllipse(transform(*pt), 2, 2)
            caption = '계산된 법선·형상 평활화의 결과 · 확대 탭에서 경계 비교'
            detail = '막의 물리적 확산이 아니라 계산에 쓰는 수치 평활화입니다.'
        else:
            maximum = max((v for data in self.fields for v in data['growth']), default=1.)
            is_ion = family == 'transmission'
            values = fields['ion'] if is_ion else fields['growth']
            for i in range(0, len(fields['points']), 3):
                x, y = fields['points'][i]; nx, ny = fields['normals'][i]; value = values[i]
                start = transform(x, y)
                length = 7+24*value/max(maximum if not is_ion else 1., 1e-12)
                end = start+QPointF(nx*length, -ny*length)
                color = '#3a84c4' if is_ion else '#088e80'
                p.setPen(QPen(QColor(color), 1)); p.drawLine(start, end)
                self.moving_dot(p, end, start, (travel+i*.13) % 1, color, 1+2*value/max(maximum, 1e-12))
            caption = '표면의 계산 배율: '+('기존 이온 전달량' if is_ion else '국소 증착 성장량')
            detail = '초기 표면의 배율을 선 길이로 표현한 개념도입니다. 선 길이는 실제 막두께가 아닙니다.'
        p.restore()
        self.label(p, caption, 290)
        self.label(p, detail, 314, '#64748b', 11)

    def draw_setting(self, p):
        """Spatial UI illustrations, never fake physical growth or flow boxes."""
        if self.draw_recipe_meaning(p):
            return
        t = (1-math.cos(2*math.pi*self.phase))/2
        rect = QRectF(30, 45, 460, 238)
        transform, scale = fit_transform((-750, -980, 750, 200), rect)
        pts = list(TRENCH)
        title, caption = '表示 설정 · 계산 형상 유지'.replace('表示', '표시'), '설명용 이미지 · 아래 적용 조건을 확인하세요.'
        if self.kind in ('coordinate_x', 'coordinate_y', 'coordinates'):
            p.setPen(QPen(QColor('#94a3b8'), 2, Qt.DashLine)); p.drawPath(path(pts, transform))
            x, y = pts[2]
            x += 150*t if self.kind != 'coordinate_y' else 0
            y -= 180*t if self.kind != 'coordinate_x' else 0
            pts[2] = (x, y)
            p.setPen(Qt.NoPen); p.setBrush(QColor('#db790c')); p.drawEllipse(transform(x, y), 5, 5)
            title, caption = '초기 구조 점 이동 예시 · 공정 성장 아님', 'X: 좌우 · Y: 위아래. 바뀐 입력 구조가 다음 계산에 사용됩니다.'
        elif self.kind == 'opacity':
            p.setPen(QPen(QColor('#94a3b8'), 2)); p.drawPath(path(pts, transform))
            color = QColor('#db790c'); color.setAlpha(int(255*t))
            p.setPen(QPen(color, 5)); p.drawPath(path(pts, transform))
            self.label(p, '겹친 표시의 진하기 변화 · 형상 좌표 그대로', 0, size=13)
            self.label(p, '투명 ← → 진함 · 표시만 달라집니다.', 302)
            return
        elif self.kind == 'frames':
            result = self.recorded_result
            if result is not None and result.frame_profiles:
                i = min(len(result.frame_profiles)-1, int(t*(len(result.frame_profiles)-1)))
                pts = result.frame_profiles[i]
                transform, scale = fit_transform(self.recorded_bounds, rect)
                for loop in result.frame_voids[i]:
                    p.setPen(QPen(QColor('#008694'),2)); p.drawPath(path(loop,transform,True))
                title = f'이미 계산된 결과 재생 · Step {result.frame_steps[i]}'
            else:
                title = '저장된 결과 없음 · 계산 후 프레임을 선택하세요'
            caption = '결과 단계는 이미 계산한 단면을 고릅니다. 재계산하거나 증착을 추가하지 않습니다.'
        elif self.key == 'spin_depth_closure_threshold':
            title = '닫힘 진단 예시 · 고정된 틈과 판정 기준 비교'
            a, b = QPointF(237, 115), QPointF(267, 115)
            p.setPen(QPen(QColor('#64748b'), 3)); p.drawLine(a, b)
            p.setPen(QColor('#87530d')); p.drawText(170, 100, '고정 틈 12 Å')
            p.drawText(165, 150, f'진단 기준 {4+16*t:.1f} Å')
            p.drawText(165, 175, '닫힘 기록' if 4+16*t >= 12 else '열림 기록')
            self.label(p, title, 0, size=13)
            self.label(p, '기록만 바뀝니다. 형상이나 실제 접촉 시점을 바꾸지 않습니다.', 304)
            return
        elif self.kind in ('split', 'sampling'):
            title = '여러 조건의 트랜치를 각각 계산해 비교'
            for i in range(3):
                small, _ = fit_transform((-750, -980, 750, 100), QRectF(10+170*i, 70, 160, 195))
                p.setPen(QPen(QColor('#008694' if i == int(self.phase*3) else '#94a3b8'), 2))
                p.drawPath(path(pts, small)); p.drawText(45+170*i, 290, f'조건 {i+1}')
            self.label(p, title, 0, size=13)
            self.label(p, '초기 구조 배치 예시입니다. 결과 형상은 Split 실행 후 계산됩니다.', 315)
            return
        p.setPen(QPen(QColor('#008694'), 2)); p.setBrush(Qt.NoBrush); p.drawPath(path(pts, transform))
        if self.kind not in ('coordinate_x', 'coordinate_y', 'coordinates', 'frames'):
            point = pts[min(len(pts)-1, int(self.phase*len(pts)))]
            p.setPen(Qt.NoPen); p.setBrush(QColor('#008694')); p.drawEllipse(transform(*point), 4, 4)
        self.label(p, title, 0, size=13)
        self.label(p, caption, 304, '#64748b', 11)

    def draw_recipe_meaning(self, p):
        """Explicit reference equations; these never impersonate trench results."""
        kinds = {'ald_cycles', 'ald_gpc', 'cvd_rate', 'cvd_time', 'process_type',
                 'recipe_model', 'growth_basis', 'sticking', 'exposure',
                 'inhibitor_sticking', 'inhibitor_exposure'}
        if self.kind not in kinds:
            return False
        phase = self.phase
        left, top, width, height = 55., 60., 420., 205.
        p.setPen(QPen(QColor('#94a3b8'), 1))
        p.drawLine(QPointF(left, top), QPointF(left, top+height))
        p.drawLine(QPointF(left, top+height), QPointF(left+width, top+height))
        if self.kind in ('exposure', 'inhibitor_exposure'):
            self.label(p, '설명용 · 평탄면의 유효 표면 피복', 0, size=13)
            for exposure, color in ((1., COLORS[0]), (5., COLORS[2])):
                points = [QPointF(left+width*i/100, top+height*math.exp(-exposure*i/100))
                          for i in range(101)]
                p.setPen(QPen(QColor(color), 2))
                curve = QPainterPath(points[0])
                for point in points[1:]:curve.lineTo(point)
                p.drawPath(curve)
                i = int(phase*100)
                p.setPen(Qt.NoPen); p.setBrush(QColor(color)); p.drawEllipse(points[i], 4, 4)
            self.label(p, '피복률 = 1 − exp(−유효 노출량) · 최대 100%', 280)
            self.label(p, '무차원 노출량의 원리 그림 · 실제 트랜치 단면이나 pulse 시간이 아님', 310, '#64748b', 11)
        elif self.kind in ('sticking', 'inhibitor_sticking'):
            self.label(p, '설명용 · 반응 가능한 표면에서의 흡착/반응확률', 0, size=13)
            for row, (probability, color) in enumerate(((.1, COLORS[0]), (.7, COLORS[2]))):
                y = 120+row*95
                p.setPen(QColor(color)); p.drawText(75, y-25, f'반응확률 {probability:g}')
                for i in range(10):
                    reactive = i < round(probability*10)
                    p.setBrush(QColor(color if reactive else '#d9e1e8'))
                    p.setPen(Qt.NoPen)
                    p.drawEllipse(QPointF(90+i*35, y+(1-phase)*12), 8, 8)
            self.label(p, '색: 표면에서 소모 · 회색: 반응하지 않아 다시 이동 가능', 280)
            self.label(p, '반응 가능한 자리의 확률 설명 · 깊이별 포집량은 구조 수송 계산으로 결정', 310, '#64748b', 11)
        elif self.kind == 'growth_basis':
            self.label(p, '설명용 · 평탄면에서 성장과 제거를 한 번씩 계산', 0, size=13)
            labels = [('식각 전 입력', 3., 1.), ('순성장 입력', 4., 1.)]
            for i, (label, growth, removal) in enumerate(labels):
                x = 150+i*205
                p.setPen(QColor('#334155')); p.drawText(x-65, 88, label)
                h = 35*(growth-removal*min(1., phase*2))
                p.setPen(Qt.NoPen); p.setBrush(QColor(COLORS[i])); p.drawRect(QRectF(x-30, 245-h, 60, h))
                p.setPen(QColor('#334155')); p.drawText(x-80, 285, f'{growth:g} 성장 − {removal:g} 제거 = {growth-removal:g}')
            self.label(p, '같은 입력 3, 평탄면 제거 1의 예시 · 트랜치 형상 예측이 아님', 310, '#64748b', 11)
        elif self.kind == 'recipe_model':
            self.label(p, '모델 선택 · 저장된 계수의 해석과 계산법 선택', 0, size=13)
            for i, text in enumerate(('Conformal: 노출면에 같은 법선 두께 성장', '수송·반응: 구조별 공급과 포화 계산', '기존 보정: SFO3.1 단면 기준 유지')):
                p.setPen(QColor(COLORS[i])); p.drawText(85, 112+i*58, text)
            self.label(p, '모델 간 정확도 순위를 뜻하지 않습니다. 다른 구조에서 검증하세요.', 305, '#64748b', 11)
            p.setPen(Qt.NoPen); p.setBrush(QColor('#008694')); p.drawEllipse(QPointF(80+phase*370, 250), 4, 4)
        else:
            ald = self.kind in ('ald_cycles', 'ald_gpc')
            self.label(p, '설명용 · 기준 평탄면 성장량의 관계식', 0, size=13)
            for multiplier, color in ((.45, COLORS[0]), (.9, COLORS[2])):
                curve = QPainterPath(QPointF(left, top+height))
                for i in range(1, 101):
                    x = i/100
                    y = math.floor(x*10)/10 if ald else x
                    curve.lineTo(QPointF(left+width*x, top+height*(1-y*multiplier)))
                p.setPen(QPen(QColor(color), 2)); p.drawPath(curve)
                y = math.floor(phase*10)/10 if ald else phase
                p.setPen(Qt.NoPen); p.setBrush(QColor(color)); p.drawEllipse(QPointF(left+width*phase, top+height*(1-y*multiplier)), 4, 4)
            equation = 'ALD: GPC × cycle 수' if ald else 'CVD: D/R × 시간'
            if self.kind == 'process_type':equation = 'ALD: GPC × cycle 수 / CVD: D/R × 시간'
            self.label(p, equation, 282)
            self.label(p, '기준량 관계식 · 실제 트랜치 두께는 수송·반응·식각에 따라 달라짐', 310, '#64748b', 11)
        return True
