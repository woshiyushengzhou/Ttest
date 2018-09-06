################################################
import imutils
import time
import logging
import traceback
import cv2
from multiprocessing.connection import Listener
from imutils.video import VideoStream
from queue import Queue
from threading import Thread
from pyzbar import pyzbar
from collections import Counter
from multiprocessing.connection import Client

# log config
log_format = '%(asctime)s %(filename)s[line:%(lineno)d] %(levelname)s %(message)s'
logging.basicConfig(level=logging.INFO, filename='raspberry2.log', format=log_format)

MES_IPADDRESS = '192.168.10.5'
Rapberry1_IPADDRESS = '192.168.10.3'


def white_balance(frame):
    wb = cv2.xphoto.createGrayworldWB()
    wb.setSaturationThreshold(0.8)
    new_frame = wb.balanceWhite(frame)
    return new_frame


def simple_color(color):
    """
    detect red yellow blue color
    :param image: imgage
    :return: center color numpyq
    """
    c = max(color)
    if color[0] == c:
        return "blue"
    if color[1] == c:
        return "green"
    if color[2] == c:
        return "red"


def color_probability(frame, x, y):
    colors = []
    for i in range(x - 25, x - 10, 1):
        color = frame[y][i]
        colors.append(simple_color(color))

    color_counts = Counter(colors)
    top_one = color_counts.most_common(1)
    return top_one[0][0]


def detect_barcode_color(image):
    """
    detect QR code
    :param image: iamge
    :return: QR code data
    """
    barcodes = pyzbar.decode(image)
    # loop over the detected barcodes
    if barcodes:
        barcode = barcodes[0]
        (x, y, w, h) = barcode.rect
        color = color_probability(image, x, y)
        # cv2.rectangle(image, (x, y), (x + w, y + h), (0, 0, 255), 2)
        qrcode = barcode.data.decode("utf-8")
        # draw the barcode data and barcode type on the image
        # text = "{}".format(qrcode)
        # cv2.putText(image, text, (x, y - 10),
        #             cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        return qrcode, color
    else:
        return None


def rainbow_lamp(rap1_c, color='green', index=None):
    """
    :param rap1_c: raspberry1 listerner server
    :param color: lamp color that camera want to camera
    :param index: cemera index
    :return: None
    """
    rap1_c.send({'color':color,'index':index})
    logging.info('Send lamp info to Raspberry1 success...')


def pre_call_camera(index, num):
    num_desc = dict([(0, 'First'), (1, 'Second'), (2, 'Third')])

    sorting = num_desc[num]
    index = index
    vs = VideoStream(src=index).start()
    time.sleep(2.0)
    logging.info("{} starting video stream on webcamera-{}...".format(sorting, index))

    for i in range(50):
        if i in (0, 49):
            logging.info('Index {} is detecting ,## {} times##'.format(index, i))
        frame = vs.read()
        frame = imutils.resize(frame, width=800)
        # cv2.imshow("Camera-{}".format(index), frame)
        cv2.waitKey(1)
        detected_info = detect_barcode_color(image=frame)

        if detected_info:
            qrcode, color = detected_info
            cv2.destroyAllWindows()
            vs.stop()
            return qrcode, color

    logging.info('{} Camera-{} exit...'.format(sorting, index))
    cv2.destroyAllWindows()
    vs.stop()
    del vs
    return None


def call_camera(signal, mes_server, rap1_client):
    """
    call camera to detect object info
    :param signal: single that call the corresponding camera
    :param mes_server: connection to mes server
    :param rap1_client: raspberry1 client
    :return:None
    """
    station_map = dict([(0, 'X'), (1, 'A1'), (2, 'A2'), (3, 'A3'), (4, 'B1'), (5, 'B2'), (6, 'B3')])
    index = signal
    station = station_map[index]

    for i in range(3):
        detected_info = pre_call_camera(index=index, num=i)
        if detected_info:
            qrcode, color = detected_info
            info_process(mc=mes_server, index=index, station=station, qrcode=qrcode, color=color)
            rainbow_lamp(rap1_c=rap1_client, color='green')
            return None
        if i != 2:
            rainbow_lamp(rap1_c=rap1_client, color='yellow')
            time.sleep(2)
    logging.info('Camera-{} detecting NO qrcode , control red lamp ...'.format(index))
    # TODO send cant get qrcode info to mes
    # TODO NO qrcode red lamp warning
    rainbow_lamp(rap1_c=rap1_client, color='red', index=index)


def info_process(mc, index, station, qrcode, color):
    """
    capture frame and detected its info,then send to raspberry pi and MES
    :param mc: mes_client
    :param frame: capture frame
    :param index: camera sec index
    :param station: the station name for related camera
    :return: None
    """
    shape = 'rectangle'
    info = dict(header=index, data={'qrcode': qrcode, 'color': color, 'shape': shape, 'station': station})
    logging.info('Camera-{} Found [Color: {} ,Shape: {} ,QRCode: {}] on station-{} '.format(index, color, shape, qrcode,
                                                                                            station))
    mc.send(info)
    logging.info('Send info to MES success')
    return None


def echo_server(out_q, address, authkey):
    serv = Listener(address, authkey=authkey)
    while True:
        try:
            client = serv.accept()
            try:
                while True:
                    msg = client.recv()
                    if 'sensor' in msg.keys():
                        # msg foramt {'sensor':1}
                        data = msg['sensor']
                        out_q.put(data)
            except EOFError:
                logging.error('Connection closed')
        except Exception:
            traceback.print_exc()


def video_capture(in_q):
    """
    video capture after calling camera
    :param in_q: queue ,shareing data with listener
    :return: None
    """
    # mes pre connection
    con_count = 1
    while True:
        try:
            mes_c = Client((MES_IPADDRESS, 25000), authkey=b'peekaboo')
            break
        # ConnectionRefusedError
        except Exception as e:
            logging.error("Can't connect MES Server ## {} times ##, error reason : {}".format(con_count,e))
            con_count += 1
            time.sleep(5)
    logging.info("Connected to MES server success ...")

    # rapberry1 pre connection
    con_count = 1
    while True:
        try:
            rap1_c = Client((Rapberry1_IPADDRESS, 25001), authkey=b'peekaboo')
            break
        # ConnectionRefusedError
        except Exception as e:
            logging.error("Can't connect Raspberry1 Server ## {} times ##, error reason : {}".format(con_count, e))
            con_count += 1
            time.sleep(5)
    logging.info("Connected to Raspberry1 server success ...")

    logging.info('Camera is ready to receive signal ...')
    while True:
        if not in_q.empty():
            signal = q.get()
            if signal in range(7):
                call_camera(signal=signal, mes_server=mes_c,rap1_client=rap1_c)
            else:
                logging.error('Incorrent signal ...')


if __name__ == "__main__":
    # Create the shared queue and launch both threads
    q = Queue(3)
    t1 = Thread(target=echo_server, args=(q, ('', 25000), b'peekaboo'))
    t2 = Thread(target=video_capture, args=(q,))
    t1.start()
    t2.start()