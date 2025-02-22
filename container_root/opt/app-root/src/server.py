import os, json, time, requests, logging, threading, re
import datetime as dt
from flask import Flask, request, jsonify, stream_with_context, Response
from flask_cors import CORS, cross_origin
from http.client import HTTPConnection
from kubernetes import client, config

##############################
# Log params
log = logging.getLogger('urllib3')
log.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
log.addHandler(ch)
HTTPConnection.debuglevel = 1

##############################
# Setup Flask Variables
flaskPort = os.environ.get("FLASK_RUN_PORT", 9876)
flaskHost = os.environ.get("FLASK_RUN_HOST", "0.0.0.0")
tlsCert = os.environ.get("FLASK_TLS_CERT", "")
tlsKey = os.environ.get("FLASK_TLS_KEY", "")
protocol = "http" if tlsCert == "" and tlsKey == "" else "https"
flaskURI = os.environ.get("FLASK_URI", protocol + "://" + flaskHost + ":" + str(flaskPort))

kubernetesServiceAddress = os.environ.get("KUBERNETES_SERVICE_HOST", "")

##############################
# Setup General Variables
loopTiming = os.environ.get("LOOP_TIMING", 90)
additionalHostConfigPath = os.environ.get("ADDITIONAL_HOST_CONFIG_PATH", "")

defaultiPXEBootScript = """#!ipxe

dhcp
shell
"""

##############################
# creates a Flask application
app = Flask(__name__)
CORS(app) # This will enable CORS for all routes

####################################################################################################
# Health check endpoint
@app.route("/healthz", methods = ['GET'])
def healthz():
    if request.method == 'GET':
        return "ok"

####################################################################################################
# Index endpoint
@app.route("/")
def index():
    return "Blue pxe styx taste best!"

infraEnvs = {}
infraEnvsByMac = {}
ipxeScriptBody = {}
macPointers = {}
macPointers['data'] = ""
ipxeScriptBody['data'] = "#!ipxe\n\ndhcp\n\n"
ipxeScriptBody['mac_scripts'] = {}

def clearGlobalVars():
    global infraEnvs
    global infraEnvsByMac
    global ipxeScriptBody
    global macPointers
    infraEnvs = {}
    infraEnvsByMac = {}
    ipxeScriptBody = {}
    macPointers = {}
    macPointers['data'] = ""
    ipxeScriptBody['data'] = "#!ipxe\n\ndhcp\n\n"
    ipxeScriptBody['mac_scripts'] = {}

def loadAdditionalHostConfig():
    if additionalHostConfigPath != "":
        try:
            # Çheck to make sure the path exists and is a directory
            if os.path.isdir(additionalHostConfigPath):
                # Load a list of all the files in the path
                files = os.listdir(additionalHostConfigPath)
                for file in files:
                    # Convert the filename to a proper MAC address
                    mac = file.replace("-", ":").lower()
                    with open(additionalHostConfigPath + "/" + file, 'r') as f:
                        data = f.read()
                        ipxeScriptBody['mac_scripts'][mac] = data
                        f.close()
            else:
                print("Error loading additional host config: Path is not a directory")
                return ""
        except Exception as e:
            print("Error loading additional host config: " + str(e))
            return ""

def processInfraEnv():

    clearGlobalVars()

    # Any additional per-host MAC-based config will be applied here
    # Then if the same MAC is defined in a BMH, the BMH/InfraEnv config will override
    # If there is a default InfraEnv, it will be set as the default boot target
    # If all else fails, an iPXE prompt will be displayed
    loadAdditionalHostConfig()

    ipxeScriptBody['data'] += "echo IP configuration:\nroute\necho ${net0/mac}\n\n"

    if kubernetesServiceAddress != "":
        config.load_incluster_config()
    else:
        config.load_kube_config()

    api = client.CustomObjectsApi()

    # get the resource and print out data
    allInfraEnvs = api.get_namespaced_custom_object(
        group="agent-install.openshift.io",
        version="v1beta1",
        namespace="",
        name="",
        plural="infraenvs",
    )
    # Loop through infraenvs
    for infraenv in allInfraEnvs['items']:
        ieScript = ""
        macScript = "#!ipxe\n\ndhcp\n\n"

        infraenvConditions = infraenv['status']['conditions']
        infraenvCondition = next((item for item in infraenvConditions if item["type"] == "ImageCreated"), None)
        if infraenvCondition is None:
            continue
        if infraenvCondition['reason'] != "ImageCreated":
            continue

        infraEnvName = infraenv['metadata']['name']
        pattern = re.compile('[\W_]+')
        safeName = pattern.sub('', infraEnvName)

        infraEnvs[infraEnvName] = {}
        infraEnvs[infraEnvName]['bootArtifacts'] = infraenv['status']['bootArtifacts']
        
        ipxeScript = requests.get(infraenv['status']['bootArtifacts']['ipxeScript'], verify=False).text
        infraEnvs[infraEnvName]['ipxeScriptRaw'] = ipxeScript

        splitiPXEScript = ipxeScript.split("\n")
        ipxeKernelSuffix = ""
        for line in splitiPXEScript:
            if "/boot-artifacts/kernel" in line:
                kernelLine = line
                kernelLineParts = kernelLine.split(" ")
                for idx, part in enumerate(kernelLineParts):
                    if ("kernel" != part) and ("/boot-artifacts/kernel" not in part) and ("/boot-artifacts/kernel" not in part) and ("initrd=initrd" != part) and ("coreos.live.rootfs_url=" not in part):
                        ipxeKernelSuffix += " " + part

        ieScript += ":" + safeName + "\n"
        ieScript += "initrd --name initrd " + str(flaskURI) + "/boot-artifacts/initrd/" + infraEnvName + "\n"
        macScript += "initrd --name initrd " + str(flaskURI) + "/boot-artifacts/initrd/" + infraEnvName + "\n"
        ieScript += "kernel " + str(flaskURI) + "/boot-artifacts/kernel/" + infraEnvName + " initrd=initrd coreos.live.rootfs_url=" + str(flaskURI) + "/boot-artifacts/rootfs/" + infraEnvName + ipxeKernelSuffix + "\n"
        macScript += "kernel " + str(flaskURI) + "/boot-artifacts/kernel/" + infraEnvName + " initrd=initrd coreos.live.rootfs_url=" + str(flaskURI) + "/boot-artifacts/rootfs/" + infraEnvName + ipxeKernelSuffix + "\n"
        ieScript += "boot\n"
        macScript += "boot\n"
        ieScript += "\n"

        infraEnvs[infraEnvName]['hosts'] = {}

        # Find the BMHs that are associated with the InfraEnv
        infraenvBMHs = api.list_cluster_custom_object(
            group="metal3.io",
            version="v1alpha1",
            plural="baremetalhosts",
            label_selector="infraenvs.agent-install.openshift.io=" + infraEnvName
        )
        for bmh in infraenvBMHs['items']:
            bmhMAC = bmh['spec']['bootMACAddress']
            infraEnvs[infraEnvName]['hosts'][bmh['metadata']['name']] = {}
            infraEnvs[infraEnvName]['hosts'][bmh['metadata']['name']]['bootMACAddress'] = bmhMAC
            macPointers['data'] += "iseq ${net0/mac} " + bmhMAC + " && goto " + safeName + " ||\n"
            infraEnvsByMac[bmhMAC.lower()] = infraEnvName
            ipxeScriptBody['mac_scripts'][bmhMAC.lower()] = macScript

        ipxeScriptBody['data'] += ieScript
    # Set the default boot target

    defaultInfraEnv = api.list_cluster_custom_object(
        group="agent-install.openshift.io",
        version="v1beta1",
        plural="infraenvs",
        label_selector="pxe-bridge-default.infraenvs.agent-install.openshift.io=true"
    )
    if len(defaultInfraEnv['items']) > 0:
        defaultInfraEnvName = defaultInfraEnv['items'][0]['metadata']['name']
        pattern = re.compile('[\W_]+')
        safeName = pattern.sub('', defaultInfraEnvName)
        macPointers['data'] += "goto " + safeName + "\n"
    else:
        pattern = re.compile('[\W_]+')
        safeName = pattern.sub('', list(infraEnvs.keys())[0])
        macPointers['data'] += "goto " + safeName + "\n"

    ipxeScriptBody['data'] += macPointers['data']


# Run the processInfraEnv function in the background every 90 seconds
def runProcessInfraEnv():
    while True:
        processInfraEnv()
        print(str(dt.datetime.now()) + " - Executed processInfraEnv, waiting for " + str(loopTiming) + " seconds")
        time.sleep(loopTiming)

####################################################################################################
@app.route('/boot-artifacts/<arttype>/<name>')
def proxyBootArtifacts(arttype, name):
    infraEnvName = str(name)
    artifactType = str(arttype)
    infraEnv = infraEnvs[infraEnvName]
    artifactPath = infraEnv['bootArtifacts'][artifactType]
    r = requests.get(artifactPath, stream=True, verify=False)
    return Response(r.iter_content(chunk_size=10*1024),
                    content_type=r.headers['Content-Type'])

# ipxeMACBootRoute
# This route will take in a MAC address and return the defined/generated iPXE script for that MAC address
# If the MAC address is not found, it will return the default iPXE script
@app.route("/ipxe-mac-boot/<mac>", methods = ['GET'])
def ipxeMACBootRoute(mac):
    if request.method == 'GET':
        # Normalize the MAC address to lowercase
        mac = mac.lower()
        macScript = ipxeScriptBody['mac_scripts'].get(mac)
        if macScript:
            return Response(macScript, mimetype='text/plain')
        else:
            return Response(defaultiPXEBootScript, mimetype='text/plain')

# proxyBootIPXEScript
# This route will take in a MAC address, and look up the associated BMH and the InfraEnv it is a part of
# It will then return the iPXE script for that InfraEnv directly without modification
# If the MAC address is not found as a BMH, it will look up for any additional host configs that may be defined
# If that does not return a result, it will return the default iPXE script
@app.route('/ipxe-mac-proxy/<mac>')
def proxyBootIPXEScript(mac):
    mac = str(mac).lower()
    # Check for the MAC address in the infraEnvsByMac dictionary
    infraEnvName = infraEnvsByMac.get(mac)
    if infraEnvName:
        infraEnv = infraEnvs[infraEnvName]
        artifactPath = infraEnv['bootArtifacts']['ipxeScript']
        r = requests.get(artifactPath, stream=True, verify=False)
        return Response(r.iter_content(chunk_size=10*1024),
                      content_type=r.headers['Content-Type'])
    else:
        # Check to see if the MAC address
        macScript = ipxeScriptBody['mac_scripts'].get(mac)
        if macScript:
            return Response(macScript, mimetype='text/plain')
        else:
            # If there is no MAC specific config found, give the default iPXE script
            return Response(defaultiPXEBootScript, mimetype='text/plain')

@app.route("/ipxe-boot", methods = ['GET'])
def ipxeBootRoute():
    if request.method == 'GET':
        return Response(ipxeScriptBody['data'], mimetype='text/plain')

@app.route("/inventory", methods = ['GET'])
def inventoryRoute():
    if request.method == 'GET':
        return json.dumps(infraEnvs)


##############################
## Start the application when the python script is run
if __name__ == "__main__":
    processThread = threading.Thread(target=runProcessInfraEnv)
    try:
        # Code that may raise KeyboardInterrupt
        processThread.start()
        if tlsCert != "" and tlsKey != "":
            print("Starting OpenShift InfraEnv iPXE Glue Service on port " + str(flaskPort) + " and host " + str(flaskHost) + " with TLS cert " + str(tlsCert) + " and TLS key " + str(tlsKey))
            app.run(ssl_context=(str(tlsCert), str(tlsKey)), port=flaskPort, host=flaskHost)
            print("Serving on " + flaskURI)
        else:
            print("Starting OpenShift InfraEnv iPXE Glue Service on port " + str(flaskPort) + " and host " + str(flaskHost))
            print("Serving on " + flaskURI)
            app.run(port=flaskPort, host=flaskHost)
    except KeyboardInterrupt:
        #processThread.terminate()
        print("Exiting...")
