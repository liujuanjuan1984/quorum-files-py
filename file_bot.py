import base64
import datetime
import hashlib
import json
import os
import time

from mixinsdk.clients.client_http import HttpClient_WithAppConfig
from mixinsdk.clients.config import AppConfig
from mixinsdk.types.message import pack_message, pack_text_data
from officy import JsonFile
from quorum_data_py import util
from quorum_mininode_py import MiniNode
from quorum_mininode_py.crypto.age import age_decrypt, age_encrypt

__version__ = "0.1.0"


class config:
    """或者放到 config.py 中并导入"""

    SEED_URL = "rum://seed?v=1&e=0&n=0&c=5yv_HYBaOLsf3tiSIdHdMrl-px7ymD30pswYK-ekYCM&g=jxceD_tzRx2d18fRD-yEmg&k=Aw2w9lzqXkQCTzKL1v0DqQXKlKYDOK5gzhHjItkla3fP&s=MqJ4YYWJVEd6l1EI9N2wM_fvSTM0ZjoicDLzBwlEBEYr1987vG8rm7jx14ebkzVLfdSX4e-GsWYpCzOYhxqVXAE&t=F7fxIV3udLw&a=testGroup&y=group_files&u=http://192.168.0.104:62726?jwt=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhbGxvd0dyb3VwIjoiOGYxNzFlMGYtZmI3My00NzFkLTlkZDctYzdkMTBmZWM4NDlhIiwiZXhwIjoxODY2Nzc5NzE3LCJuYW1lIjoiYWxsb3ctOGYxNzFlMGYtZmI3My00NzFkLTlkZDctYzdkMTBmZWM4NDlhIiwicm9sZSI6Im5vZGUifQ.dZsYK4JI-9gwwX_-wosWKG_t5HpfDnDsmPWweYJQ9k8"

    PVTKEY = "0x7xxxxxx...xxxx99"  # 或通过系统环境变量设定，下同。
    AGE_PVTKEY = "AGE-SECRET-KEY-1xx..xx0X"
    AGE_PUBKEYS = ["agexx..xx", "agexx..xx"]
    MIXIN_BOT_KEYSTORE = {
        "client_id": "xx..xx",
        "session_id": "xx..xx",
        "private_key": "xx..xx",
        "pin": "xx..xx",
        "pin_token": "xx..xx",
    }
    ADMIN_MIXIN_ID = "xx..xx"
    HTTP_ZEROMESH = "https://mixin-api.zeromesh.net"


class FileBot:
    """
    通过轻节点 api 往 public group 存储加密过的 file 数据切片，及还原数据切片为 file。
    """

    def __init__(self):
        """通过 config.ini 来管理环境变量"""

        self.rum = MiniNode(config.SEED_URL, config.PVTKEY, config.AGE_PVTKEY)
        if self.rum.account.age_pubkey not in config.AGE_PUBKEYS:
            config.AGE_PUBKEYS.append(self.rum.account.age_pubkey)
        mixin_config = AppConfig.from_payload(config.MIXIN_BOT_KEYSTORE)
        self.xin = HttpClient_WithAppConfig(mixin_config, api_base=config.HTTP_ZEROMESH)

    def tell_admin(self, text: str):
        self.xin.api.send_messages(
            pack_message(
                pack_text_data(text),
                conversation_id=self.xin.get_conversation_id_with_user(
                    config.ADMIN_MIXIN_ID
                ),
            )
        )

    def upload(
        self,
        file_path: str,
        need_zip: bool = True,
        memo: str = None,
        age_pubkeys: list = config.AGE_PUBKEYS,
    ):
        """往链上写入数据"""

        if need_zip:
            file_path = util.zip_file(file_path)
        progress_file = f"upload_{datetime.date.today()}.json"
        progress = JsonFile(progress_file).read({})
        if file_path not in progress:
            # TODO: 对文件数据进行加密，然后再切片
            file_bytes, fileinfo = util.init_fileinfo(file_path, memo=memo)
            encrypted = age_encrypt(age_pubkeys, file_bytes)
            pieces = util.split_file_to_pieces(encrypted, fileinfo)
            progress[file_path] = pieces
            JsonFile(progress_file).write(progress)
            self.tell_admin(f"{file_path} split to {len(pieces)} pieces")
        else:
            pieces = progress[file_path]

        for piece in pieces:
            if piece.get("status") != "DONE":
                trx_id = piece["trx_id"]
                trx = self.rum.api.get_trx(trx_id)
                if trx.get("Data"):
                    piece["status"] = "DONE"
                    self.tell_admin(f"{piece['name']}: {trx_id} upload success")
                else:
                    copy = piece.copy()
                    del copy["trx_id"]
                    self.rum.api.post_content(copy, trx_id)
                    piece["status"] = str(datetime.datetime.now())
                    self.tell_admin(f"{piece['name']}: {trx_id} upload start")
                JsonFile(progress_file).write(progress)

        all_is_done = True
        for piece in pieces:
            if piece.get("status") != "DONE":
                all_is_done = False

        if all_is_done:
            self.tell_admin(f"{file_path} upload success")
            if str(datetime.date.today()) not in progress_file:
                os.remove(progress_file)
                self.tell_admin(f"{progress_file} is removed")
            return True

    def merge_trxs_to_file(self, file_dir: str, info: dict):
        ifilepath = os.path.join(file_dir, info["name"])
        if os.path.exists(ifilepath):
            return ifilepath

        encrypted = b""
        for seg in info["segments"]:
            trx = self.rum.api.trx(seg["trx_id"])
            if not trx:
                raise ValueError("trx not exist", trx["TrxId"])
            content = base64.b64decode(trx["Data"]["content"])
            csha = hashlib.sha256(content).hexdigest()
            if csha != seg["sha256"]:
                raise ValueError("sha256 not match")
            if trx["Data"]["name"] != seg["id"]:
                raise ValueError("seg name not match")

            encrypted += base64.b64decode(trx["Data"]["content"])

        decrypted = age_decrypt(self.rum.account.age_pvtkey, encrypted)
        with open(ifilepath, "wb") as f:
            f.write(decrypted)
        self.tell_admin(f"{ifilepath}, downloaded!")
        return ifilepath

    def download(self, to_dir: str = None):
        dl_progress_file = os.path.join(to_dir, "download_progress.json")
        progress = JsonFile(dl_progress_file).read({"start_trx": None, "files": {}})
        start_trx = progress.get("start_trx", None)
        today_todir = os.path.join(to_dir, str(datetime.date.today()))
        if not os.path.exists(today_todir):
            os.makedirs(today_todir)

        print(today_todir, "start...")

        while True:
            trxs = self.rum.api.get_content(
                start_trx=start_trx, num=20, senders=[self.rum.account.pubkey]
            )
            if not trxs:
                break
            for trx in trxs:
                if trx.get("Data", {}).get("name") == "fileinfo":
                    info = json.loads(trx["Data"]["content"])
                    if trx["TrxId"] not in progress["files"]:
                        progress["files"][trx["TrxId"]] = {"info": info}
                    if "local" not in progress["files"][trx["TrxId"]]:
                        result = self.merge_trxs_to_file(today_todir, info)
                        if result:
                            progress["files"][trx["TrxId"]]["local"] = result
                    JsonFile(dl_progress_file).write(progress)
                start_trx = trx["TrxId"]
                progress["start_trx"] = trx["TrxId"]
                print("update start_trx", start_trx)

        JsonFile(dl_progress_file).write(progress)


if __name__ == "__main__":
    bot = FileBot()
    base_dir = os.path.dirname(__file__)
    task_progress_file = os.path.join(base_dir, "backup_task_progress.json")
    progress = JsonFile(task_progress_file).read({})
    tasks = {
        "/home/ubuntu/test/bootstrap-3.4.1.zip": {
            "times": "ONCE",
            "need_zip": False,
            "memo": "bootstrap",
        },
        "/home/ubuntu/test/data.db": {
            "times": "DAILY",
            "need_zip": True,
            "memo": "data.db of testbot",
        },
        "/home/ubuntu/test/quorum_data_py-1.2.7-py3-none-any.whl": {
            "times": "WEEKLY",
            "need_zip": True,
            "memo": "whl of quorum_data_py",
        },
    }
    print("task start.")
    for file_path, item in tasks.items():
        need_upload = False
        if file_path not in progress:
            need_upload = True
        elif item["times"] == "DAILY":
            last_time = datetime.datetime.strptime(
                progress[file_path]["upload_at"], "%Y-%m-%d %H:%M:%S.%f"
            )
            next_time = last_time + datetime.timedelta(days=1)
            if datetime.datetime.now() >= next_time:
                need_upload = True
        elif item["times"] == "WEEKLY":
            last_time = datetime.datetime.strptime(
                progress[file_path]["upload_at"], "%Y-%m-%d %H:%M:%S.%f"
            )
            next_time = last_time + datetime.timedelta(days=7)
            if datetime.datetime.now() >= next_time:
                need_upload = True
        print(file_path, "need upload:", need_upload)
        if need_upload:
            for i in range(18000):
                done = bot.upload(
                    file_path,
                    need_zip=item["need_zip"],
                    memo=item["memo"],
                    age_pubkeys=config.AGE_PUBKEYS,
                )
                if done:
                    progress[file_path] = {"upload_at": str(datetime.datetime.now())}
                    JsonFile(task_progress_file).write(progress)
                    break
                time.sleep(3)

    to_dir = os.path.join(base_dir, "download")
    if not os.path.exists(to_dir):
        os.makedirs(to_dir)
    bot.download(to_dir=to_dir)
