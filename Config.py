import json


class Config:
    """
    Класс конфигурации, загружающий параметры из JSON-файла.
    Реализован как Singleton для глобального доступа к настройкам.
    """

    def __init__(self, config_path: str = "config.json") -> None:
        """
        Инициализирует конфигурацию из указанного JSON-файла.
        Конструктор вызывается только один раз благодаря SingletonMeta.

        :param config_path: Путь к файлу конфигурации.
        """

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                raw_config = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Файл конфигурации не найден: {config_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Некорректный JSON в файле {config_path}: {e}")

        # Валидация обязательных полей
        required_keys = {"api_key", "port", "lang", "img2txt_prompt"}
        missing = required_keys - raw_config.keys()
        if missing:
            raise ValueError(f"В конфигурации отсутствуют обязательные ключи: {missing}")

        # Типизация и сохранение
        self.api_key: str = raw_config["api_key"]
        self.port: int = int(raw_config["port"])
        self.lang: str = raw_config["lang"]
        self.img2txt_prompt: str = raw_config["img2txt_prompt"]


    def __repr__(self) -> str:
        return (
            f"Config(api_key='***', port={self.port}, "
            f"lang='{self.lang}', img2txt_prompt='{self.img2txt_prompt}')"
        )