"""
Модуль для генерации изображений профилей пользователей
"""
from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional, List, Dict, Any
from PIL import Image, ImageDraw, ImageFont
import colorsys
import os
import platform
import logging

logger = logging.getLogger(__name__)


def _load_cyrillic_font(size: int) -> ImageFont.FreeTypeFont:
    """
    Загружает шрифт с поддержкой кириллицы, доступный на Windows и Linux
    
    Args:
        size: Размер шрифта
        
    Returns:
        ImageFont.FreeTypeFont: Загруженный шрифт
        
    Raises:
        OSError: Если не удалось найти ни один подходящий шрифт
    """
    # Список шрифтов для проверки (в порядке приоритета)
    font_names = [
        "DejaVuSans",
        "DejaVu Sans",
        "LiberationSans-Regular",
        "Liberation Sans",
        "arial",
        "Arial",
        "Tahoma",
        "tahoma",
    ]
    
    # Расширения файлов шрифтов
    font_extensions = [".ttf", ".TTF"]
    
    # Определяем платформу и пути к шрифтам
    system = platform.system()
    font_paths = []
    
    if system == "Windows":
        # Windows системные шрифты
        windows_font_dir = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
        font_paths.append(windows_font_dir)
    elif system == "Linux":
        # Linux системные шрифты
        font_paths.extend([
            "/usr/share/fonts/truetype/dejavu",
            "/usr/share/fonts/truetype/liberation",
            "/usr/share/fonts/TTF",
            "/usr/share/fonts/truetype",
            "/usr/local/share/fonts",
            os.path.expanduser("~/.fonts"),
        ])
    
    # Также проверяем локальный путь (Noto Sans)
    local_font_path = "data/fonts/NotoSans-Regular.ttf"
    if os.path.exists(local_font_path):
        try:
            return ImageFont.truetype(local_font_path, size)
        except Exception:
            pass
    
    # Перебираем шрифты и пути
    for font_name in font_names:
        for font_path_dir in font_paths:
            if not os.path.exists(font_path_dir):
                continue
                
            for ext in font_extensions:
                # Пробуем разные варианты имени файла
                possible_names = [
                    f"{font_name}{ext}",
                    f"{font_name.replace(' ', '')}{ext}",
                    f"{font_name.replace(' ', '-')}{ext}",
                ]
                
                for name in possible_names:
                    font_path = os.path.join(font_path_dir, name)
                    if os.path.exists(font_path):
                        try:
                            return ImageFont.truetype(font_path, size)
                        except Exception as e:
                            logger.debug(f"Не удалось загрузить шрифт {font_path}: {e}")
                            continue
        
        # Также пробуем прямой путь без расширения (для PIL, который может найти системный шрифт)
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            continue
    
    # Если ничего не найдено, пробуем найти любой доступный шрифт через fontconfig (Linux)
    if system == "Linux":
        try:
            import subprocess
            result = subprocess.run(
                ["fc-match", "DejaVu Sans:style=Regular", "-f", "%{file}"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                font_file = result.stdout.strip()
                if os.path.exists(font_file):
                    return ImageFont.truetype(font_file, size)
        except Exception:
            pass
    
    # Если ничего не сработало, генерируем ошибку
    raise OSError(
        f"Не удалось найти шрифт с поддержкой кириллицы. "
        f"Проверьте наличие DejaVu Sans, Liberation Sans, Arial или Tahoma в системе."
    )


def generate_modern_profile_card(
    user_data: Dict[str, Any],
    monthly_stats: List[Dict[str, Any]],
    avatar_path: Optional[str] = None
) -> BytesIO:
    """
    Генерация современного графика профиля пользователя за месяц в темной теме
    
    Args:
        user_data: Данные пользователя (не используется)
        monthly_stats: Статистика за 30 дней
        avatar_path: Путь к файлу аватарки (не используется)
    
    Returns:
        BytesIO: Буфер с изображением PNG
    """
    # Размеры графика в ультра-широком формате (увеличенное разрешение для лучшего качества)
    width, height = 2880, 960  # Увеличено в 1.5 раза
    padding = 120  # Пропорционально увеличено
    
    # Создаем основное изображение с темно-серым фоном
    image = Image.new('RGB', (width, height), '#374151')
    draw = ImageDraw.Draw(image)
    
    # Загружаем шрифты (с поддержкой кириллицы)
    try:
        font_title = _load_cyrillic_font(32)
        font_medium = _load_cyrillic_font(20)
        font_small = _load_cyrillic_font(16)
        font_tiny = _load_cyrillic_font(14)
    except OSError as e:
        logger.error(f"Ошибка загрузки шрифта с поддержкой кириллицы: {e}")
        # В критическом случае пробуем загрузить через PIL напрямую
        # но это может не поддерживать кириллицу
        try:
            font_title = ImageFont.truetype("arial.ttf", 32)
            font_medium = ImageFont.truetype("arial.ttf", 20)
            font_small = ImageFont.truetype("arial.ttf", 16)
            font_tiny = ImageFont.truetype("arial.ttf", 14)
        except Exception:
            # Последняя попытка - но это может не работать с кириллицей
            logger.warning("Используется запасной шрифт, кириллица может отображаться некорректно")
            font_title = ImageFont.load_default()
            font_medium = ImageFont.load_default()
            font_small = ImageFont.load_default()
            font_tiny = ImageFont.load_default()
    
    # Добавляем заголовок
    title = "Ваша активность за 30 дней"
    title_bbox = draw.textbbox((0, 0), title, font=font_title)
    title_width = title_bbox[2] - title_bbox[0]
    draw.text(((width - title_width) // 2, 20), title, fill='#ffffff', font=font_title)
    
    # Создаем график
    chart_x = padding
    chart_y = 70
    chart_width = width - padding * 2
    chart_height = height - chart_y - padding
    
    _create_modern_chart(draw, monthly_stats, chart_x, chart_y, chart_width, chart_height,
                        font_medium, font_small, font_tiny)
    
    # Подпись оси Y (вертикальная) - переворачиваем текст
    y_label = "Сообщений"
    y_label_bbox = draw.textbbox((0, 0), y_label, font=font_small)
    y_label_width = y_label_bbox[2] - y_label_bbox[0]
    y_label_height = y_label_bbox[3] - y_label_bbox[1]
    
    # Создаем временное изображение для поворота текста
    temp_img = Image.new('RGBA', (y_label_width, y_label_height), (0, 0, 0, 0))
    temp_draw = ImageDraw.Draw(temp_img)
    temp_draw.text((0, 0), y_label, fill='#ffffff', font=font_small)
    
    # Поворачиваем на 90 градусов
    rotated_img = temp_img.rotate(90, expand=True)
    
    # Вставляем повернутый текст
    image.paste(rotated_img, (15, (height - rotated_img.height) // 2), rotated_img)
    
    # Подпись оси X (горизонтальная)
    x_label = "Дата"
    x_label_bbox = draw.textbbox((0, 0), x_label, font=font_small)
    x_label_width = x_label_bbox[2] - x_label_bbox[0]
    draw.text(((width - x_label_width) // 2, height - 30), x_label, fill='#ffffff', font=font_small)
    
    # Сохраняем в буфер с максимальным качеством
    buf = BytesIO()
    image.save(buf, format='PNG', optimize=False)  # Без оптимизации для максимального качества
    buf.seek(0)
    return buf




def _round_to_nice_number(value: float) -> int:
    """
    Округляет число до ближайшего "красивого" числа из ряда: 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000...
    Всегда округляет вверх для большего шага.
    
    Args:
        value: Число для округления
        
    Returns:
        int: Округленное "красивое" число (всегда >= value)
    """
    if value <= 0:
        return 1
    
    # Определяем порядок величины
    magnitude = 10 ** (len(str(int(value))) - 1)
    
    # Нормализуем значение (приводим к диапазону 1-10)
    normalized = value / magnitude
    
    # Выбираем ближайшее "красивое" число (всегда округляем вверх)
    if normalized <= 1:
        nice = 1
    elif normalized <= 2:
        nice = 2
    elif normalized <= 5:
        nice = 5
    else:
        nice = 10
        magnitude *= 10
    
    result = nice * magnitude
    
    # Если результат меньше исходного значения, увеличиваем на порядок
    if result < value:
        if nice == 1:
            nice = 2
        elif nice == 2:
            nice = 5
        elif nice == 5:
            nice = 10
            magnitude *= 10
        result = nice * magnitude
    
    return result


def _get_top_bar_color_by_activity(count: int, max_val: int, is_max: bool = False) -> str:
    """
    Вычисляет цвет верхушки столбца на основе его активности
    
    Args:
        count: Количество сообщений за день
        max_val: Максимальное значение активности среди всех дней
        is_max: Флаг, указывающий, является ли этот день самым активным
        
    Returns:
        str: Цвет в формате HEX (светло-голубая палитра для верхушки, оранжевый для максимального)
    """
    if count == 0:
        return '#E0F2FE'  # Очень светлый голубой для нулевой активности
    
    # Если это самый активный день, используем оранжевый цвет
    if is_max:
        # Оранжевый цвет (HSV: hue=30, насыщенный и яркий)
        hue = 30  # Оранжевый оттенок
        saturation = 0.85  # Высокая насыщенность
        value = 1.0  # Максимальная яркость
        r, g, b = colorsys.hsv_to_rgb(hue/360, saturation, value)
        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
    
    # Нормализуем активность от 0 до 1
    normalized = min(count / max_val, 1.0)
    
    # Используем более линейную функцию для лучшего распределения градиента
    # Используем квадратный корень для небольшого сглаживания, но сохраняем различия
    intensity = normalized ** 0.5  # Более линейный переход для лучшей видимости различий
    
    # Базовый светло-голубой цвет (HSV: hue=195)
    # Расширяем диапазон насыщенности и яркости для лучшей видимости различий
    hue = 195  # Голубой оттенок
    # Насыщенность: от 20% (очень светлый) до 85% (яркий) - больший диапазон
    saturation = 0.2 + (intensity * 0.65)  # От 20% до 85% насыщенности
    # Яркость: от 85% (светлый) до 100% (яркий) - больший диапазон
    value = 0.85 + (intensity * 0.15)  # От 85% до 100% яркости
    
    # Конвертируем HSV в RGB, затем в HEX
    r, g, b = colorsys.hsv_to_rgb(hue/360, saturation, value)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def _create_modern_chart(draw: ImageDraw.Draw, monthly_stats: List[Dict[str, Any]], 
                        x: int, y: int, width: int, height: int,
                        font_medium: ImageFont, font_small: ImageFont, font_tiny: ImageFont):
    """Создание современного графика активности за месяц в темной теме"""
    # Подготовка данных
    days = []
    counts = []
    
    # Заполняем данные за последние 30 дней
    def _safe_count(v):
        try:
            n = int(v or 0)
            return n if n > 0 else 0
        except Exception:
            return 0

    date_index = {d["date"]: _safe_count(d.get("message_count")) for d in monthly_stats}
    
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        date_str = day.strftime('%Y-%m-%d')
        days.append(date_str)
        counts.append(_safe_count(date_index.get(date_str, 0)))
    
    # Максимальное значение для масштабирования - используем реальные данные
    max_count_actual = max(counts) if counts and max(counts) > 0 else 1
    
    # Добавляем небольшой запас сверху для лучшего отображения (10% от максимального значения)
    max_val = int(max_count_actual * 1.1) + 1
    
    # Адаптивная сетка с оптимальным количеством линий (4-5)
    target_lines = 4  # Целевое количество линий сетки (меньше = больше шаг)
    step = max_val / target_lines
    
    # Округляем шаг до "красивого" числа (всегда округляем вверх для большего шага)
    nice_step = _round_to_nice_number(step)
    
    # Если шаг получился слишком маленьким (меньше 1% от max_val), увеличиваем его
    if nice_step < max_val * 0.01:
        nice_step = _round_to_nice_number(max_val * 0.15)  # Минимум 15% от max_val
    
    # Генерируем значения сетки с красивым шагом
    grid_values = []
    current = 0
    while current <= max_val:
        grid_values.append(int(current))
        current += nice_step
        # Защита от бесконечного цикла
        if len(grid_values) > 20:
            break
    
    # Убираем дубликаты и сортируем
    grid_values = sorted(list(set(grid_values)))
    
    # Ограничиваем максимальное количество линий до 8
    if len(grid_values) > 8:
        # Берем каждую N-ю линию
        step_indices = len(grid_values) // 8
        grid_values = [grid_values[i] for i in range(0, len(grid_values), max(step_indices, 1))]
    
    for value in grid_values:
        y_pos = y + height - (value / max_val) * height
        
        # Сетка (более прозрачная)
        draw.line([x, y_pos, x + width, y_pos], fill='#6b7280', width=1)
        
        # Подписи значений на оси Y
        label = str(value)
        label_bbox = draw.textbbox((0, 0), label, font=font_small)
        label_width = label_bbox[2] - label_bbox[0]
        label_height = label_bbox[3] - label_bbox[1]
        draw.text((x - label_width - 10, y_pos - label_height // 2), 
                 label, fill='#ffffff', font=font_small)
    
    # Вычисляем параметры столбцов
    bar_spacing = width / 30
    bar_width = bar_spacing * 0.8  # Ширина столбца
    
    # Рисуем столбцы
    for i, (day, count) in enumerate(zip(days, counts)):
        try:
            bar_x = x + i * bar_spacing + (bar_spacing - bar_width) / 2
            
            if count > 0:
                bar_height_px = (count / max_val) * height
            else:
                bar_height_px = 0
                
            # Нормализуем координаты столбца и приводим к целым значениям
            y_bottom = int(y + height)
            y_top_float = (y + height) - bar_height_px
            y_top = int(y_top_float) if y_top_float <= y_bottom else y_bottom
            if y_top < y:
                y_top = y
            
            # Определяем, является ли этот день самым активным
            # Используем реальное максимальное значение, а не max_val (который включает запас сверху)
            is_max_day = (count == max_count_actual and count > 0)
            
            # Вычисляем цвет верхушки столбца на основе активности дня
            top_color = _get_top_bar_color_by_activity(count, max_val, is_max_day)
            base_color = '#ffffff'  # Белый цвет для всего столбца
            
            # Рисуем столбец без обводки с закругленными верхними углами
            # Рисуем даже столбцы с нулевой активностью (с минимальной высотой для видимости)
            if bar_width > 0 and y_top <= y_bottom:
                # Для нулевой активности рисуем минимальную высоту (2px) для видимости
                if bar_height_px == 0:
                    bar_height_px = 2
                    y_top = y_bottom - bar_height_px
                
                # Радиус закругления (пропорционально ширине столбца, но не больше 8px)
                radius = min(int(bar_width * 0.15), 8)
                
                # Сначала рисуем весь столбец белым с закругленными верхними углами
                _draw_rounded_top_rectangle(draw, 
                                           (int(bar_x), int(y_top), int(bar_x + bar_width), int(y_bottom)), 
                                           fill=base_color, 
                                           radius=radius)
                
                # Теперь рисуем верхушку столбца (голубая часть) поверх белого
                # Высота верхушки - 15% от общей высоты, но не меньше 3px и не больше самой высоты
                top_height = min(max(int(bar_height_px * 0.15), 3), bar_height_px)
                top_y_bottom = y_bottom
                top_y_top = y_bottom - top_height
                
                # Рисуем верхушку с закругленными верхними углами
                if top_height >= radius * 2:
                    _draw_rounded_top_rectangle(draw, 
                                               (int(bar_x), int(top_y_top), int(bar_x + bar_width), int(top_y_bottom)), 
                                               fill=top_color, 
                                               radius=radius)
                else:
                    # Для очень маленьких столбцов рисуем простой прямоугольник
                    draw.rectangle([int(bar_x), int(top_y_top), int(bar_x + bar_width), int(top_y_bottom)], 
                                  fill=top_color)
                
                # Добавляем текст с количеством сообщений поверх столбца
                if count > 0:
                    count_text = str(count)
                    count_bbox = draw.textbbox((0, 0), count_text, font=font_tiny)
                    count_width = count_bbox[2] - count_bbox[0]
                    count_height = count_bbox[3] - count_bbox[1]
                    
                    # Позиционируем текст над столбцом
                    text_x = int(bar_x + (bar_width - count_width) / 2)
                    text_y = int(max(y + 2, y_top - count_height - 5))
                    
                    # Текст белого цвета
                    draw.text((text_x, text_y), count_text, fill='#ffffff', font=font_tiny)
        except Exception:
            # Пропускаем проблемный столбец, чтобы не срывать генерацию всего изображения
            continue
        
        # Подписи дат под осью (каждые 3 дня для лучшей читаемости)
        if i % 3 == 0 or i == len(days) - 1:
            date_label = datetime.strptime(day, '%Y-%m-%d').strftime('%d.%m')
            date_bbox = draw.textbbox((0, 0), date_label, font=font_tiny)
            date_width = date_bbox[2] - date_bbox[0]
            # Поворачиваем даты на 45 градусов для лучшей читаемости
            temp_img = Image.new('RGBA', (date_width + 20, 20), (0, 0, 0, 0))
            temp_draw = ImageDraw.Draw(temp_img)
            temp_draw.text((0, 0), date_label, fill='#ffffff', font=font_tiny)
            rotated_img = temp_img.rotate(-45, expand=True)
            image = draw._image
            image.paste(rotated_img, 
                       (int(bar_x + (bar_width - rotated_img.width) / 2), 
                        int(y + height + 5)), 
                       rotated_img)
    
    # Рисуем рамку графика (после столбцов, чтобы была поверх)
    draw.rectangle([x, y, x + width, y + height], outline='#9ca3af', width=2)
    
    # Рисуем основные оси (после столбцов, чтобы были поверх)
    draw.line([x, y, x, y + height], fill='#9ca3af', width=2)  # Вертикальная ось Y
    draw.line([x, y + height, x + width, y + height], fill='#9ca3af', width=2)  # Горизонтальная ось X (нижний контур)


def _lighten_color(hex_color: str, factor: float) -> str:
    """Осветляет цвет на заданный фактор"""
    # Убираем # если есть
    hex_color = hex_color.lstrip('#')
    
    # Конвертируем в RGB
    r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    # Конвертируем в HSV
    h, s, v = colorsys.rgb_to_hsv(r/255.0, g/255.0, b/255.0)
    
    # Увеличиваем яркость
    v = min(1.0, v + factor)
    
    # Конвертируем обратно в RGB
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    
    # Возвращаем в hex
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def _darken_color(hex_color: str, factor: float) -> str:
    """Затемняет цвет на заданный фактор"""
    # Убираем # если есть
    hex_color = hex_color.lstrip('#')
    
    # Конвертируем в RGB
    r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    # Конвертируем в HSV
    h, s, v = colorsys.rgb_to_hsv(r/255.0, g/255.0, b/255.0)
    
    # Уменьшаем яркость
    v = max(0.0, v - factor)
    
    # Конвертируем обратно в RGB
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    
    # Возвращаем в hex
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def _desaturate_color(hex_color: str, factor: float) -> str:
    """Уменьшает насыщенность цвета на заданный фактор"""
    # Убираем # если есть
    hex_color = hex_color.lstrip('#')
    
    # Конвертируем в RGB
    r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    # Конвертируем в HSV
    h, s, v = colorsys.rgb_to_hsv(r/255.0, g/255.0, b/255.0)
    
    # Уменьшаем насыщенность
    s = max(0.0, s * (1 - factor))
    
    # Конвертируем обратно в RGB
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    
    # Возвращаем в hex
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def generate_activity_chart(
    activity_data: List[Dict[str, Any]],
    title: str = "Активность",
    subtitle: str = "",
    x_label: str = "Время",
    is_hourly: bool = True
) -> BytesIO:
    """
    Генерация графика активности по часам или дням
    
    Args:
        activity_data: Список данных активности [{'label': '00:00', 'count': 10}, ...]
        title: Заголовок графика
        subtitle: Подзаголовок графика
        x_label: Подпись оси X
        is_hourly: True для часового графика, False для дневного
    
    Returns:
        BytesIO: Буфер с изображением PNG
    """
    # Размеры графика
    width, height = 2880, 960
    padding = 120
    
    # Создаем основное изображение с темно-серым фоном
    image = Image.new('RGB', (width, height), '#374151')
    draw = ImageDraw.Draw(image)
    
    # Загружаем шрифты
    try:
        font_title = _load_cyrillic_font(32)
        font_subtitle = _load_cyrillic_font(20)
        font_medium = _load_cyrillic_font(20)
        font_small = _load_cyrillic_font(16)
        font_tiny = _load_cyrillic_font(14)
    except OSError as e:
        logger.error(f"Ошибка загрузки шрифта: {e}")
        try:
            font_title = ImageFont.truetype("arial.ttf", 32)
            font_subtitle = ImageFont.truetype("arial.ttf", 20)
            font_medium = ImageFont.truetype("arial.ttf", 20)
            font_small = ImageFont.truetype("arial.ttf", 16)
            font_tiny = ImageFont.truetype("arial.ttf", 14)
        except Exception:
            font_title = ImageFont.load_default()
            font_subtitle = ImageFont.load_default()
            font_medium = ImageFont.load_default()
            font_small = ImageFont.load_default()
            font_tiny = ImageFont.load_default()
    
    # Заголовок
    title_y = 20
    title_bbox = draw.textbbox((0, 0), title, font=font_title)
    title_width = title_bbox[2] - title_bbox[0]
    draw.text(((width - title_width) // 2, title_y), title, fill='#ffffff', font=font_title)
    
    # Подзаголовок
    if subtitle:
        subtitle_y = title_y + 50
        subtitle_bbox = draw.textbbox((0, 0), subtitle, font=font_subtitle)
        subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
        draw.text(((width - subtitle_width) // 2, subtitle_y), subtitle, fill='#9ca3af', font=font_subtitle)
    
    if not activity_data:
        no_data_text = "Нет данных для отображения"
        no_data_bbox = draw.textbbox((0, 0), no_data_text, font=font_medium)
        no_data_width = no_data_bbox[2] - no_data_bbox[0]
        draw.text(((width - no_data_width) // 2, height // 2), no_data_text, fill='#9ca3af', font=font_medium)
        buf = BytesIO()
        image.save(buf, format='PNG', optimize=False)
        buf.seek(0)
        return buf
    
    # Область графика
    chart_x = padding + 100  # Место для подписи оси Y
    chart_y = (subtitle_y + 80) if subtitle else (title_y + 80)
    chart_width = width - chart_x - padding
    chart_height = height - chart_y - padding - 50
    
    # Подготовка данных
    labels = [item['label'] for item in activity_data]
    counts = [item['count'] for item in activity_data]
    max_count_actual = max(counts) if counts and max(counts) > 0 else 1
    
    # Добавляем небольшой запас сверху для лучшего отображения (10% от максимального значения)
    max_val = int(max_count_actual * 1.1) + 1
    
    # Адаптивная сетка с оптимальным количеством линий (4-5)
    target_lines = 4
    step = max_val / target_lines
    
    # Округляем шаг до "красивого" числа
    nice_step = _round_to_nice_number(step)
    
    # Если шаг получился слишком маленьким, увеличиваем его
    if nice_step < max_val * 0.01:
        nice_step = _round_to_nice_number(max_val * 0.15)
    
    # Генерируем значения сетки
    grid_values = []
    current = 0
    while current <= max_val:
        grid_values.append(int(current))
        current += nice_step
        if len(grid_values) > 20:
            break
    
    # Убираем дубликаты и сортируем
    grid_values = sorted(list(set(grid_values)))
    
    # Ограничиваем максимальное количество линий до 8
    if len(grid_values) > 8:
        step_indices = len(grid_values) // 8
        grid_values = [grid_values[i] for i in range(0, len(grid_values), max(step_indices, 1))]
    
    # Рисуем сетку
    for value in grid_values:
        y_pos = chart_y + chart_height - (value / max_val) * chart_height
        
        # Сетка (пунктирная)
        draw.line([chart_x, y_pos, chart_x + chart_width, y_pos], fill='#6b7280', width=1)
        
        # Подписи значений на оси Y
        label = str(value)
        label_bbox = draw.textbbox((0, 0), label, font=font_small)
        label_width = label_bbox[2] - label_bbox[0]
        label_height = label_bbox[3] - label_bbox[1]
        draw.text((chart_x - label_width - 10, y_pos - label_height // 2), 
                 label, fill='#ffffff', font=font_small)
    
    # Подпись оси Y (вертикальная) - переворачиваем текст
    y_label = "Сообщений"
    y_label_bbox = draw.textbbox((0, 0), y_label, font=font_small)
    y_label_width = y_label_bbox[2] - y_label_bbox[0]
    y_label_height = y_label_bbox[3] - y_label_bbox[1]
    
    # Создаем временное изображение для поворота текста
    temp_img = Image.new('RGBA', (y_label_width, y_label_height), (0, 0, 0, 0))
    temp_draw = ImageDraw.Draw(temp_img)
    temp_draw.text((0, 0), y_label, fill='#ffffff', font=font_small)
    
    # Поворачиваем на 90 градусов
    rotated_img = temp_img.rotate(90, expand=True)
    
    # Вставляем повернутый текст
    image.paste(rotated_img, (15, (height - rotated_img.height) // 2), rotated_img)
    
    # Параметры столбцов
    num_items = len(activity_data)
    bar_spacing = chart_width / num_items if num_items > 0 else 0
    bar_width = bar_spacing * 0.8
    
    # Рисуем столбцы
    for i, (label, count) in enumerate(zip(labels, counts)):
        bar_x = chart_x + i * bar_spacing + (bar_spacing - bar_width) / 2
        
        if count > 0:
            bar_height_px = (count / max_val) * chart_height
        else:
            bar_height_px = 0
        
        y_bottom = int(chart_y + chart_height)
        y_top_float = (chart_y + chart_height) - bar_height_px
        y_top = int(y_top_float) if y_top_float <= y_bottom else y_bottom
        if y_top < chart_y:
            y_top = chart_y
        
        # Для нулевой активности рисуем минимальную высоту
        if bar_height_px == 0:
            bar_height_px = 2
            y_top = y_bottom - bar_height_px
        
        # Определяем, является ли этот период самым активным
        is_max = (count == max_count_actual and count > 0)
        
        # Цвет верхушки
        top_color = _get_top_bar_color_by_activity(count, max_count_actual, is_max)
        base_color = '#ffffff'
        
        # Радиус закругления
        radius = min(int(bar_width * 0.15), 8)
        
        # Рисуем весь столбец белым
        _draw_rounded_top_rectangle(draw, 
                                   (int(bar_x), int(y_top), int(bar_x + bar_width), int(y_bottom)), 
                                   fill=base_color, 
                                   radius=radius)
        
        # Рисуем верхушку
        top_height = min(max(int(bar_height_px * 0.15), 3), int(bar_height_px))
        top_y_bottom = y_bottom
        top_y_top = y_bottom - top_height
        if top_height >= radius * 2:
            _draw_rounded_top_rectangle(draw, 
                                       (int(bar_x), int(top_y_top), int(bar_x + bar_width), int(top_y_bottom)), 
                                       fill=top_color, 
                                       radius=radius)
        else:
            draw.rectangle([int(bar_x), int(top_y_top), int(bar_x + bar_width), int(top_y_bottom)], 
                          fill=top_color)
        
        # Подписи под столбцами (каждые N для читаемости)
        if is_hourly:
            show_label = (i % 3 == 0 or i == num_items - 1)
        else:
            show_label = (i % 5 == 0 or i == num_items - 1)
        
        if show_label:
            label_bbox = draw.textbbox((0, 0), label, font=font_tiny)
            label_width = label_bbox[2] - label_bbox[0]
            label_x = int(bar_x + (bar_width - label_width) / 2)
            draw.text((label_x, y_bottom + 5), label, fill='#ffffff', font=font_tiny)
    
    # Рисуем рамку графика (после столбцов, чтобы была поверх)
    draw.rectangle([chart_x, chart_y, chart_x + chart_width, chart_y + chart_height], outline='#9ca3af', width=2)
    
    # Рисуем основные оси (после столбцов, чтобы были поверх)
    draw.line([chart_x, chart_y, chart_x, chart_y + chart_height], fill='#9ca3af', width=2)  # Вертикальная ось Y
    draw.line([chart_x, chart_y + chart_height, chart_x + chart_width, chart_y + chart_height], fill='#9ca3af', width=2)  # Горизонтальная ось X
    
    # Подпись оси X
    x_label_bbox = draw.textbbox((0, 0), x_label, font=font_small)
    x_label_width = x_label_bbox[2] - x_label_bbox[0]
    draw.text(((width - x_label_width) // 2, height - 30), x_label, fill='#ffffff', font=font_small)
    
    # Сохраняем в буфер
    buf = BytesIO()
    image.save(buf, format='PNG', optimize=False)
    buf.seek(0)
    return buf


async def generate_top_chart(
    top_users: List[Dict[str, Any]],
    title: str = "Топ активных пользователей",
    subtitle: str = "",
    bot_instance = None
) -> BytesIO:
    """
    Генерация графика топ пользователей
    
    Args:
        top_users: Список пользователей с полями user_id, message_count, username, first_name
        title: Заголовок графика
        subtitle: Подзаголовок графика
    
    Returns:
        BytesIO: Буфер с изображением PNG
    """
    # Размеры графика (16:9)
    width, height = 2880, 1620  # Формат 16:9 для горизонтальных столбцов
    padding = 120
    
    # Создаем основное изображение с темно-серым фоном
    image = Image.new('RGB', (width, height), '#374151')
    draw = ImageDraw.Draw(image)
    
    # Добавляем декоративные элементы на фон
    # Вертикальные линии для глубины
    for i in range(5):
        x = width // 6 * (i + 1)
        draw.line([x, 0, x, height], fill='#4b5563', width=1)
    
    # Горизонтальные линии
    for i in range(3):
        y = height // 4 * (i + 1)
        draw.line([0, y, width, y], fill='#4b5563', width=1)
    
    # Декоративные круги в углах
    circle_size = 200
    circle_alpha = 30  # Прозрачность через цвет
    
    # Левый верхний угол
    draw.ellipse([-circle_size//2, -circle_size//2, circle_size//2, circle_size//2], 
                fill='#4b5563', outline=None)
    # Правый верхний угол
    draw.ellipse([width - circle_size//2, -circle_size//2, width + circle_size//2, circle_size//2], 
                fill='#4b5563', outline=None)
    # Левый нижний угол
    draw.ellipse([-circle_size//2, height - circle_size//2, circle_size//2, height + circle_size//2], 
                fill='#4b5563', outline=None)
    # Правый нижний угол
    draw.ellipse([width - circle_size//2, height - circle_size//2, width + circle_size//2, height + circle_size//2], 
                fill='#4b5563', outline=None)
    
    # Загружаем шрифты
    try:
        font_title = _load_cyrillic_font(40)
        font_subtitle = _load_cyrillic_font(24)
        font_medium = _load_cyrillic_font(20)
        font_small = _load_cyrillic_font(16)
        font_tiny = _load_cyrillic_font(14)
    except OSError as e:
        logger.error(f"Ошибка загрузки шрифта: {e}")
        try:
            font_title = ImageFont.truetype("arial.ttf", 40)
            font_subtitle = ImageFont.truetype("arial.ttf", 24)
            font_medium = ImageFont.truetype("arial.ttf", 20)
            font_small = ImageFont.truetype("arial.ttf", 16)
            font_tiny = ImageFont.truetype("arial.ttf", 14)
        except Exception:
            font_title = ImageFont.load_default()
            font_subtitle = ImageFont.load_default()
            font_medium = ImageFont.load_default()
            font_small = ImageFont.load_default()
            font_tiny = ImageFont.load_default()
    
    # Заголовок
    title_y = 40
    title_bbox = draw.textbbox((0, 0), title, font=font_title)
    title_width = title_bbox[2] - title_bbox[0]
    draw.text(((width - title_width) // 2, title_y), title, fill='#ffffff', font=font_title)
    
    # Подзаголовок
    if subtitle:
        subtitle_y = title_y + 60
        subtitle_bbox = draw.textbbox((0, 0), subtitle, font=font_subtitle)
        subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
        draw.text(((width - subtitle_width) // 2, subtitle_y), subtitle, fill='#9ca3af', font=font_subtitle)
    
    if not top_users:
        # Если нет данных, показываем сообщение
        no_data_text = "Нет данных для отображения"
        no_data_bbox = draw.textbbox((0, 0), no_data_text, font=font_medium)
        no_data_width = no_data_bbox[2] - no_data_bbox[0]
        draw.text(((width - no_data_width) // 2, height // 2), no_data_text, fill='#9ca3af', font=font_medium)
        buf = BytesIO()
        image.save(buf, format='PNG', optimize=False)
        buf.seek(0)
        return buf
    
    # Подготовка данных
    max_count = max(user['message_count'] for user in top_users) if top_users else 1
    max_count_actual = max_count
    
    # Область графика
    avatar_size = 60  # Размер аватарки
    chart_x = padding + avatar_size + 20 + 200  # Место для аватарок и подписей пользователей
    chart_y = (subtitle_y + 80) if subtitle else (title_y + 100)
    chart_width = width - chart_x - padding
    chart_height = height - chart_y - padding - 30  # Уменьшили отступ снизу
    
    # Количество пользователей для отображения
    num_users = len(top_users)
    bar_height = (chart_height - (num_users - 1) * 10) / num_users  # 10px между столбцами
    bar_height = min(bar_height, 80)  # Максимальная высота столбца
    
    # Получаем аватары параллельно для всех пользователей
    avatar_images = {}
    if bot_instance:
        async def get_avatar(user_id: int):
            try:
                photos = await bot_instance.get_user_profile_photos(user_id, limit=1)
                if photos and photos.total_count > 0:
                    file = await bot_instance.get_file(photos.photos[0][-1].file_id)
                    avatar_bytes = await bot_instance.download_file(file.file_path)
                    avatar_img = Image.open(avatar_bytes)
                    avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
                    # Создаем круглую маску
                    mask = Image.new('L', (avatar_size, avatar_size), 0)
                    mask_draw = ImageDraw.Draw(mask)
                    mask_draw.ellipse([0, 0, avatar_size, avatar_size], fill=255)
                    avatar_img.putalpha(mask)
                    return user_id, avatar_img
            except Exception as e:
                logger.debug(f"Не удалось загрузить аватар для пользователя {user_id}: {e}")
            return user_id, None
        
        # Получаем все аватары параллельно
        import asyncio
        tasks = [get_avatar(user['user_id']) for user in top_users]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, tuple) and len(result) == 2:
                user_id, avatar_img = result
                if avatar_img:
                    avatar_images[user_id] = avatar_img
    
    # Рисуем столбцы
    for i, user in enumerate(top_users):
        count = user['message_count']
        user_id = user['user_id']
        user_name = user.get('first_name', '') or user.get('username', f"ID{user_id}") or f"ID{user_id}"
        if len(user_name) > 20:
            user_name = user_name[:17] + "..."
        
        # Позиция столбца
        bar_y = chart_y + i * (bar_height + 10)
        bar_x = chart_x
        
        # Ширина столбца
        if max_count > 0:
            bar_width = (count / max_count) * chart_width
        else:
            bar_width = 0
        
        # Определяем, является ли этот пользователь самым активным
        is_max = (count == max_count_actual and count > 0)
        
        # Цвет верхушки
        top_color = _get_top_bar_color_by_activity(count, max_count, is_max)
        base_color = '#ffffff'
        
        # Высота верхушки (15% от высоты столбца, минимум 3px)
        top_height = min(max(int(bar_height * 0.15), 3), int(bar_height))
        
        # Рисуем весь столбец белым с закругленными углами со всех сторон
        # Радиус закругления (15% от высоты, но не больше 8px, минимум 3px для видимости)
        radius = max(3, min(int(bar_height * 0.15), 8))
        
        if bar_width > 0:
            # Вычисляем реальный радиус с учетом размеров столбца
            actual_radius = min(radius, max(1, int(bar_width / 2)), max(1, int(bar_height / 2)))
            
            # Рисуем столбец с закруглениями, если размеры позволяют
            if actual_radius >= 1 and bar_width >= 2 and bar_height >= 2:
                _draw_rounded_rectangle(draw, 
                                       (int(bar_x), int(bar_y), int(bar_x + bar_width), int(bar_y + bar_height)), 
                                       fill=base_color, 
                                       radius=actual_radius)
            else:
                # Если столбец слишком узкий или маленький, рисуем без закруглений
                draw.rectangle([int(bar_x), int(bar_y), int(bar_x + bar_width), int(bar_y + bar_height)], 
                              fill=base_color)
        
        # Рисуем верхушку столбца с закруглениями
        if bar_width > 0:
            top_y_bottom = int(bar_y + bar_height)
            top_y_top = int(bar_y + bar_height - top_height)
            
            # Вычисляем радиус для верхушки
            top_radius = min(radius, max(1, int(bar_width / 2)), max(1, int(top_height / 2)))
            
            # Рисуем верхушку с закруглениями, если размеры позволяют
            if top_radius >= 1 and top_height >= 2 and bar_width >= 2:
                _draw_rounded_rectangle(draw,
                                       (int(bar_x), int(top_y_top), int(bar_x + bar_width), int(top_y_bottom)),
                                       fill=top_color,
                                       radius=top_radius)
            else:
                # Если верхушка слишком маленькая, рисуем без закруглений
                draw.rectangle([int(bar_x), int(top_y_top), int(bar_x + bar_width), int(top_y_bottom)], 
                              fill=top_color)
        
        # Рисуем аватарку пользователя
        avatar_x = padding
        avatar_y = int(bar_y + (bar_height - avatar_size) / 2)
        
        if user_id in avatar_images:
            # Используем загруженный аватар
            image.paste(avatar_images[user_id], (avatar_x, avatar_y), avatar_images[user_id])
        else:
            # Рисуем дефолтный аватар с инициалами
            _draw_default_avatar(draw, avatar_x, avatar_y, avatar_size, user_name, font_small)
        
        # Подпись пользователя справа от аватарки
        name_bbox = draw.textbbox((0, 0), user_name, font=font_small)
        name_height = name_bbox[3] - name_bbox[1]
        name_y = int(bar_y + (bar_height - name_height) / 2)
        name_x = avatar_x + avatar_size + 10
        draw.text((name_x, name_y), user_name, fill='#ffffff', font=font_small)
        
        # Количество сообщений - внутри белого столбца справа
        count_text = f"{count} сообщ."
        count_bbox = draw.textbbox((0, 0), count_text, font=font_medium)
        count_width = count_bbox[2] - count_bbox[0]
        count_height = count_bbox[3] - count_bbox[1]
        
        # Размещаем внутри столбца справа с отступом
        padding_inside = 10
        count_x = int(bar_x + bar_width - count_width - padding_inside)
        count_y = int(bar_y + (bar_height - count_height) / 2)
        
        # Если столбец слишком узкий, размещаем справа от столбца
        if bar_width < count_width + padding_inside * 2:
            count_x = int(bar_x + bar_width + 10)
            # Используем темный цвет текста для лучшей видимости на фоне графика
            draw.text((count_x, count_y), count_text, fill='#9ca3af', font=font_medium)
        else:
            # Рисуем текст внутри столбца темным цветом для контраста с белым фоном
            draw.text((count_x, count_y), count_text, fill='#374151', font=font_medium)
    
    # Сохраняем в буфер
    buf = BytesIO()
    image.save(buf, format='PNG', optimize=False)
    buf.seek(0)
    return buf


def _draw_rounded_rectangle(draw: ImageDraw.Draw, xy: tuple, fill: str, radius: int = 5):
    """
    Рисует прямоугольник с закругленными углами со всех сторон
    
    Args:
        draw: ImageDraw объект
        xy: Кортеж (x1, y1, x2, y2) координаты прямоугольника
        fill: Цвет заливки
        radius: Радиус закругления углов
    """
    x1, y1, x2, y2 = xy
    
    # Если высота или ширина меньше радиуса * 2, используем меньший радиус
    height = y2 - y1
    width = x2 - x1
    if height < radius * 2:
        radius = max(1, height // 2)
    if width < radius * 2:
        radius = max(1, width // 2)
    
    # Если радиус стал 0 или отрицательным, рисуем обычный прямоугольник
    if radius <= 0:
        draw.rectangle([x1, y1, x2, y2], fill=fill)
        return
    
    # Рисуем основной прямоугольник (без углов)
    if x1 + radius < x2 - radius and y1 + radius < y2 - radius:
        draw.rectangle([x1 + radius, y1 + radius, x2 - radius, y2 - radius], fill=fill)
    
    # Рисуем закругленные углы с помощью эллипсов
    # Левый верхний угол
    if radius > 0:
        draw.ellipse([x1, y1, x1 + radius * 2, y1 + radius * 2], fill=fill)
    # Правый верхний угол
    if radius > 0:
        draw.ellipse([x2 - radius * 2, y1, x2, y1 + radius * 2], fill=fill)
    # Левый нижний угол
    if radius > 0:
        draw.ellipse([x1, y2 - radius * 2, x1 + radius * 2, y2], fill=fill)
    # Правый нижний угол
    if radius > 0:
        draw.ellipse([x2 - radius * 2, y2 - radius * 2, x2, y2], fill=fill)
    
    # Заполняем прямоугольники между эллипсами
    if x1 + radius < x2 - radius:
        draw.rectangle([x1 + radius, y1, x2 - radius, y1 + radius], fill=fill)  # Верх
        draw.rectangle([x1 + radius, y2 - radius, x2 - radius, y2], fill=fill)  # Низ
    if y1 + radius < y2 - radius:
        draw.rectangle([x1, y1 + radius, x1 + radius, y2 - radius], fill=fill)  # Лево
        draw.rectangle([x2 - radius, y1 + radius, x2, y2 - radius], fill=fill)  # Право


def _draw_rounded_top_rectangle(draw: ImageDraw.Draw, xy: tuple, fill: str, radius: int = 5):
    """
    Рисует прямоугольник с закругленными верхними углами
    
    Args:
        draw: ImageDraw объект
        xy: Кортеж (x1, y1, x2, y2) координаты прямоугольника
        fill: Цвет заливки
        radius: Радиус закругления углов
    """
    x1, y1, x2, y2 = xy
    
    # Если высота меньше радиуса, используем меньший радиус
    height = y2 - y1
    if height < radius * 2:
        radius = height // 2
    
    # Если ширина меньше радиуса * 2, используем меньший радиус
    width = x2 - x1
    if width < radius * 2:
        radius = width // 2
    
    # Рисуем основной прямоугольник (без верхних углов)
    draw.rectangle([x1, y1 + radius, x2, y2], fill=fill)
    
    # Рисуем закругленные верхние углы с помощью эллипсов
    # Левый верхний угол
    draw.ellipse([x1, y1, x1 + radius * 2, y1 + radius * 2], fill=fill)
    # Правый верхний угол
    draw.ellipse([x2 - radius * 2, y1, x2, y1 + radius * 2], fill=fill)
    
    # Заполняем прямоугольник между эллипсами
    draw.rectangle([x1 + radius, y1, x2 - radius, y1 + radius], fill=fill)


def _draw_default_avatar(draw: ImageDraw.Draw, x: int, y: int, size: int, name: str, font: ImageFont.FreeTypeFont):
    """
    Рисует дефолтный аватар с инициалами пользователя
    
    Args:
        draw: ImageDraw объект
        x, y: Координаты верхнего левого угла
        size: Размер аватара
        name: Имя пользователя для получения инициалов
        font: Шрифт для текста
    """
    # Цвета для дефолтных аватаров (на основе хеша имени)
    colors = [
        '#EF4444', '#F97316', '#F59E0B', '#EAB308', '#84CC16',
        '#22C55E', '#10B981', '#14B8A6', '#06B6D4', '#0EA5E9',
        '#3B82F6', '#6366F1', '#8B5CF6', '#A855F7', '#D946EF',
        '#EC4899', '#F43F5E'
    ]
    
    # Получаем инициалы из имени
    initials = ""
    if name:
        words = name.split()
        if len(words) >= 2:
            initials = (words[0][0] + words[1][0]).upper()
        elif len(words) == 1:
            initials = words[0][0].upper()
            if len(words[0]) > 1:
                initials += words[0][1].upper()
        else:
            initials = "??"
    else:
        initials = "??"
    
    # Выбираем цвет на основе хеша имени
    color_index = hash(name) % len(colors)
    bg_color = colors[color_index]
    
    # Рисуем круглый фон
    draw.ellipse([x, y, x + size, y + size], fill=bg_color)
    
    # Рисуем инициалы
    text_bbox = draw.textbbox((0, 0), initials, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    text_x = x + (size - text_width) // 2
    text_y = y + (size - text_height) // 2
    draw.text((text_x, text_y), initials, fill='#ffffff', font=font)


