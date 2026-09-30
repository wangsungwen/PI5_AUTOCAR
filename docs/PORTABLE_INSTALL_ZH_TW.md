# 不綁定 hostname／帳號的 Pi 安裝

`hostname` 是主機名稱，`username` 是登入帳號。例如 `alice@car01` 中，
`alice` 是帳號，`car01` 是 hostname。兩者都不必叫 `rpi5`。
舊版限制來自寫死的服務帳號、群組及 `/home/rpi5`，新版已移除這些限制。

## 從壓縮包安裝

仍適用 Raspberry Pi 5、64-bit Raspberry Pi OS，以及專案原有相機、I²C 與硬體設定。
「通用」指帳號與主機名稱可不同，並非可在任意作業系統或硬體上安裝。

1. 在 Raspberry Pi Imager 設定自己的帳號與 hostname，完成 OS 與網路設定。
2. 將 `RPI5_AutoCAR-YOLO-integrated.zip` 複製到 Pi 的家目錄。
   在電腦上傳時，將 `alice` 與 `192.168.1.50` 換成自己的帳號、Pi IP：

   ```bash
   scp RPI5_AutoCAR-YOLO-integrated.zip alice@192.168.1.50:~/
   ssh alice@192.168.1.50
   ```

3. 在 Pi 解壓縮並執行安裝，不需要先設定可執行權限：

   ```bash
   sudo apt-get update
   sudo apt-get install -y unzip
   mkdir -p ~/RPI5_AutoCAR
   unzip -o ~/RPI5_AutoCAR-YOLO-integrated.zip -d ~/RPI5_AutoCAR
   cd ~/RPI5_AutoCAR
   sudo bash scripts/install.sh
   ```

安裝器從 `SUDO_USER` 取得帳號，從系統帳號資料取得真正家目錄與主要群組；
不假設家目錄一定是 `/home/<帳號>`，也不假設群組名與帳號相同。
`scripts/install_pi.sh` 仍可使用，與新入口執行相同流程。
若在 root shell 或自動化部署環境執行，必須指定既有非 root 帳號：

```bash
bash scripts/install.sh alice
```

從一般帳號也可使用 `sudo bash scripts/install.sh alice` 指定服務帳號。
安裝器不會建立新帳號或修改 hostname。服務會加入系統已存在的
`gpio`、`i2c`、`video`、`render` 補充群組以存取裝置。
`deploy/autocar.service` 是模板，請透過安裝器產生，不要直接複製至 systemd。

## 路徑與連線

| 項目 | 位置／行為 |
|---|---|
| 程式與模型 | `/opt/autocar`、`/opt/autocar/models` |
| Python 環境 | `/opt/autocar-venv` |
| 環境設定 | `/etc/autocar.env` |
| 服務執行帳號 | sudo 發起者，或指令指定的帳號 |
| 新安裝的錄影目錄 | 該帳號真正家目錄下的 `Videos/autocar` |
| 監聽位址 | `AUTOCAR_HOST=0.0.0.0`，不綁定 hostname |
| 控制頁面 | `http://<Pi-IP>:8000`，若有改 port 則使用設定值 |

在 Pi 執行 `hostname -I` 查 IP。區域網路支援 mDNS 時，也可使用
`http://<自己的hostname>.local:8000`。多台 Pi 應各自使用不同 hostname。

```bash
systemctl status autocar --no-pager
systemctl show autocar -p User -p Group -p SupplementaryGroups
sudo journalctl -u autocar -n 50 --no-pager
```

壓縮包不包含模型；模型部署仍依 README 與原教學進行。

## 舊版升級

重新執行安裝器會更新服務帳號並重啟服務，但保留既有 `/etc/autocar.env`。
若其中仍有 `AUTOCAR_RECORDINGS=/home/rpi5/Videos/autocar`，該值會繼續生效。
當你改用另一個帳號時，使用 `sudo nano /etc/autocar.env` 刪除或註解該行，
即可回到新服務帳號的預設錄影目錄；也可設定另一個該帳號可寫入的絕對路徑。
舊錄影不會自動搬移；其他模型與硬體參數也不會被覆寫。修改後執行：

```bash
sudo systemctl restart autocar
```

舊教學中的 `rpi5@192.168.0.160` 與 `/home/rpi5` 是原測試機範例，
實際安裝請以本文件為準。`deploy/rpi5-update/update.sh` 是原測試環境的
增量更新工具，仍含該環境 IP，不是本通用安裝流程的一部分。
