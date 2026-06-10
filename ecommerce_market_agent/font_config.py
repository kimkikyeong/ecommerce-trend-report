"""
공통 폰트 설정 모듈
- matplotlib: NanumGothic.ttf 등록 후 기본 폰트로 적용
- plotly: NanumGothic 폰트 패밀리 반환
프로젝트 루트의 fonts/ 폴더에 NanumGothic.ttf 가 있어야 합니다.
"""

from pathlib import Path
import matplotlib as mpl
import matplotlib.font_manager as fm

# 프로젝트 루트 기준 fonts/ 경로
_FONTS_DIR = Path(__file__).parent.parent / "fonts"
_FONT_PATH = _FONTS_DIR / "NanumGothic.ttf"

_FONT_REGISTERED = False


def setup_matplotlib() -> str:
    """matplotlib 에 NanumGothic 을 등록하고 기본 폰트로 설정합니다.
    반환값: 등록된 폰트 이름 (rcParams 에 사용)
    """
    global _FONT_REGISTERED

    if not _FONT_PATH.exists():
        raise FileNotFoundError(
            f"NanumGothic.ttf 를 찾을 수 없습니다: {_FONT_PATH}\n"
            "프로젝트 루트의 fonts/ 폴더에 파일을 확인하세요."
        )

    if not _FONT_REGISTERED:
        fm.fontManager.addfont(str(_FONT_PATH))
        _FONT_REGISTERED = True

    font_name = fm.FontProperties(fname=str(_FONT_PATH)).get_name()

    mpl.rcParams["font.family"] = font_name
    mpl.rcParams["axes.unicode_minus"] = False

    return font_name


def get_plotly_font() -> dict:
    """plotly 레이아웃에 주입할 font 딕셔너리를 반환합니다.

    사용 예시:
        fig.update_layout(**font_config.get_plotly_font())
    """
    return {
        "font": {
            "family": "NanumGothic, Malgun Gothic, Apple SD Gothic Neo, sans-serif",
            "size": 13,
        }
    }
