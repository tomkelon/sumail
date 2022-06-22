from datetime import datetime
import sys
import random
import socks 
import queue
import socket
from smtplib import SMTP
import time
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
#from email.mime.base import MIMEBase
#from email import encoders
import os

class MassMailerConfig:
    totalThreads=0 #how many total threads are running
    fromName="" #sender's name
    subject="" #subject of eamil to send
    body="" #body of email to send
    maxEmailsToSend=0 #maximum number of emails to send before stopping
    sendWithProxy=True #True if we want to send using proxy server

class MassMailerSmtp:
    MAX_TRIES=5 #static variable for maximum number of failed attemps before this smtp server is dropped
    ip="smtp.gmail.com" #ip address of smtp server
    port=587 #port of smtp server (default set to 25)
    email=""
    username="" 
    password="" 
    host="gmail.com" #host part of smtp server
    requiresAuthentication=True #whether this smtp server requires authentication or not
    useTls=True #use tls or not
    has_port_opened=True #whether it has a port opened for connection or not

class MassMailerProxy:
    ip="" #ip address of proxy server
    port=0 #port of proxy server
    proxy_type="" #type of proxy (socks4,socks5,http)
    has_port_opened=False #whether it has a port opened for connection or not

class EmailToSend:
    MAX_TRIES=20 #static variable for maximum number of failed attempts email address can have before getting dropped
    Mail = "" #email address
    Tries = 0 #how many failed attempts so far
    Attachments=[] #file attachments
    
class MassMailerThreadConfig:
    threadIndex=0 #index of this thread
    config:MassMailerConfig #global config object

class MassMailerThreadState:
    threadTag="" #unique tag for this thread to identify in log
    smtp:MassMailerSmtp #current smtp server used by the thread
    smtpTryCount=0 #how many tries this thread has attempted with the current smtp server
    proxy:MassMailerProxy #current proxy server used by the thread
    proxyTryCount=0 #how many tries this thread has attempted with the current proxy server
    config:MassMailerConfig #global config object

#helper method to write log to the file and output on screen
def write_mysmtp_log(txt,meta="",write_to_file=False,write_to_screen=False):
    if (not write_to_file and not write_to_screen):
        return
    now = datetime.now()
    ct=now.strftime("%b-%d-%Y %H:%M:%S")
    if (meta!=""):
        meta=meta+"::"
    cstr=ct+"::"+meta+txt
    if (write_to_screen):
        print(cstr)
    if (write_to_file):
        logFile.write(cstr+"\n")
        logFile.flush()

#helper method to check if maximum number of emails specified in global MassMailerSmtpConfig are sent
def check_max_emails_sent(stateObject:MassMailerThreadState,tconfig:MassMailerThreadConfig):
    if (stateObject.config.maxEmailsToSend!=-1 and totalEmailsSent[0]>=stateObject.config.maxEmailsToSend):
        write_mysmtp_log("Max emails sent: "+str(totalEmailsSent[0])+","+str(stateObject.config.maxEmailsToSend),stateObject.threadTag,True,True)
        return True

    return False

#helper method to check if :port is opened on :ip
#max_attempts: how many connection attempts to make to check whether the port is opened
def check_host(ip,port,timeout=2,current_count=0,max_attempts=2):
    a_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    a_socket.settimeout(timeout)
    location = (ip,port)
    try:
        result_of_check = a_socket.connect_ex(location)
        a_socket.close()
        if result_of_check == 0:
            return True
        else:
            current_count+=1
            if (result_of_check==10035 and current_count<max_attempts):
                time.sleep(0.5)
                return check_host(ip,port,timeout,current_count,max_attempts)
            return False
    except Exception as err:
        return False

#method to load global configuration
#this must be the very first method called before doing any email sending operation
def load_config():
    my_tag="CONFIG"
    config.totalThreads=20 #number of total threads to run
    config.fromName="Vu Nhat Vuong" #body of emails
    config.maxEmailsToSend=100000 #maximum number of emails to send
    config.subject="Xin chao" #subject of emails
    config.body="Co ve ok roi day" #body of emails
    
    write_mysmtp_log("Reading SMTPs...",my_tag,False,False)
    #load smtps from smtps.txt file
    fp=open("smtps.txt","r")
    lines=fp.readlines()
    for p in lines:
        p=p.strip()
        #p must be in this format
        #ip_address(:port optional),email,password,1(or 0 for no authentication)
        vals=p.split(",")
        pr=MassMailerSmtp()
        ip_port=vals[0].strip()
        pr.email=vals[1].strip()
        #split email address (aaa@ddd.com) to get username(aaa) and host part (ddd.com)
        emailVals=pr.email.split("@")
        pr.username=emailVals[0] #username part of email
        pr.host=emailVals[1] #host part of email
        pr.password=vals[2].strip() #password
        ipvals=ip_port.split(":") #split ip:port values to get ip and port separate
        pr.ip=ipvals[0].strip() #ip address
        if (len(ipvals)>1): #if port was specified
            pr.port=int(ipvals[1])
        else:
            #default port=25
            pr.port=25
        #by default set requiresAuthentication to False
        pr.requiresAuthentication=False
        #if last value of line is 1 then authentication is required
        if (vals[3]=="1"):
            pr.requiresAuthentication=True
        #add smtp server to the queue
        smtpsQueue.put_nowait(pr)
    fp.close()
    write_mysmtp_log("SMTPs detected: "+str(smtpsQueue.qsize()),my_tag,True,True)

    write_mysmtp_log("Reading emails...",my_tag,False,False)
    #load recipients email addresses from emails.txt file
    fp=open("emails.txt","r")
    #read all lines
    lines=fp.readlines()
    for p in lines:
        p=p.strip()
        #email address per line
        pr=EmailToSend()
        pr.Mail=p #email address
        pr.Tries=0 #number of failed attempts (0 to start)
        #add email to the queue
        emailsQueue.put_nowait(pr)
    fp.close()
    write_mysmtp_log("Emails detected: "+str(emailsQueue.qsize()),my_tag,True,True)

    write_mysmtp_log("Reading proxies...",my_tag,False,False)
    fp=open("proxies.txt","r")
    lines=fp.readlines()
    proxiesQueue=[]
    for p in lines:
        p=p.strip()
        vals=p.split("#")
        pr=MassMailerProxy()
        ip_port=vals[0].strip()
        proxy_type=vals[1].strip()
        ipvals=ip_port.split(":")
        pr.ip=ipvals[0].strip()
        pr.port=int(ipvals[1])
        pr.proxy_type=proxy_type.lower()
        proxiesQueue.append(pr)
    fp.close()
    write_mysmtp_log("Proxies detected: "+str(len(proxiesQueue)),my_tag,True,True)

#helper function to get name of file from full path
def get_filename_from_path(filepath:str):
    return os.path.basename(filepath)

#base class to send emails
class EmailSender:
    config:MassMailerConfig #config object
    smtp:MassMailerSmtp #smtp to use to send email
    email:EmailToSend #recipient's email
    proxy:MassMailerProxy #proxy server to use to send email

    subject="" #subject to use
    body="" #body to use
    
    def __init__(self,config: MassMailerConfig):
        self.config=config
        self.server=False #set server variable to False

    #child classes must call this after they have instantiate a new SMTP object
    def _new_server_instance(self):
        #0 to not output any debug message
        #3 to output all debug messages
        self.server.set_debuglevel(0)

    def close_server(self):
        try:
            self.server.close()
        except Exception as err:
            pass

    #set smtp server to use with this instance
    def set_smtp_server(self,smtp:MassMailerSmtp):
        self.smtp=smtp
        if (not self.server is False):
            self.close_server()
        self.server=False #reset server to False

    def set_proxy_server(self,pxy:MassMailerProxy):
        self.proxy=pxy
        if (not self.server is False):
            self.close_server()
        self.server=False

    #set recipient's email to use with this instance
    def set_email_to_send(self,em:EmailToSend):
        self.email=em
        #process_subject_and_body is called everytime recipient is changed
        self.process_subject_and_body()

    def process_subject_and_body(self):
        self.subject=self.config.subject #set subject to the subject in global configuration
        self.body=self.config.body #set body to the body in global configuration
        #here you can perform any modification on subject and body
        #for example if you want to personalize subject and body according to the recipient's email address
        #PLEASE DO NOT MODIFY self.config.body and self.config.subject

    #helper method to construct the complete SMTP body that is sent after "DATA" command
    def build_complete_body(self):
        #from header in the form "SENDER NAME <senderemail@domain.com>"
        fromHeader="From: "+self.config.fromName+" <"+self.smtp.email+">"
        #to header simply set email address of the recipient
        toHeader="To: "+self.email.Mail
        #SMTP body is in the form
        #header1: value1\r\nheader2: value2\r\n\r\n[messagebody]
        completeBody=fromHeader+"\r\n"+toHeader+"\r\n"+"Subject: "+self.subject+"\r\nMIME-Version: 1.0\r\nContent-type: text/html; charset=utf-8\r\n"
        completeBody+="\r\n"+self.body #empty line(\r\n) after headers and then message body
        return completeBody

    def send_email(self):
        #set from in the form "SENDER NAME <senderemail@domain.com>"
        myfrom=self.config.fromName+" <"+self.smtp.email+">"
        #set to as recipient's email address
        myto=self.email.Mail
        #set body
        body = self.body
        #set subject
        subject = self.subject
        #construct a multipart message object
        msg = MIMEMultipart()
        #sender email
        msg['From'] = myfrom
        #recipient email
        msg['To'] = myto
        #subject of email
        msg['Subject'] = subject
        #add body as MIME text/html object
        msg.attach(MIMEText(body, 'html'))
        #if there are attachments in the email object
        if (len(self.email.Attachments)>0):
            #loop through each attachment
            for x in self.email.Attachments:
                #x will contain file path of the attachment file
                #get file name from file path
                fname=get_filename_from_path(x)
                #add the attachment as content/octet-stream
                att = MIMEApplication(open(x,'rb').read())
                #add header for filename
                att.add_header('content-disposition','attachment',filename=fname)
                #attach the mime par to the message object
                msg.attach(att)
        #convert msg to string
        text = msg.as_string()
        #in case of tls
        if (self.smtp.useTls):
            #send EHLO command
            self.server.ehlo()
            #start tls
            self.server.starttls()
        #login if needed
        if (self.smtp.requiresAuthentication):
            self.server.login(self.smtp.username,self.smtp.password)
        #send to server 
        self.server.sendmail(myfrom,myto,text) 

#child class of EmailSender to send emails without proxy
class NonProxyEmailSender(EmailSender):
    def __init__(self,config:MassMailerConfig):
        super().__init__(config)

    #override send_email function of base EmailSender class
    def send_email(self):
        #if server is not initialized
        if (self.server==False):
            #create instance of smtplib.SMTP with timeout of 10 seconds
            self.server = SMTP(host=self.smtp.ip,port=self.smtp.port,timeout=10)
            super()._new_server_instance()
        #call base EmailSender send_email
        super().send_email()

#ProxyEmailSender class for future if we add proxy support
class ProxyEmailSender(EmailSender):
    def __init__(self,config:MassMailerConfig):
        super().__init__(config)

    def send_email(self):
        if (self.server==False):
            self.proxy_type=socks.PROXY_TYPE_SOCKS4
            if (self.proxy.proxy_type=="socks5"):
                self.proxy_type=socks.PROXY_TYPE_SOCKS5
            elif(self.proxy.proxy_type=="http"):
                self.proxy_type=socks.PROXY_TYPE_HTTP
            self.server = SMTP(host=self.smtp.ip,port=self.smtp.port,proxy_host=self.proxy.ip,proxy_port=self.proxy.port,proxy_type=self.proxy_type,timeout=15)
            super()._new_server_instance()
        #call base EmailSender send_email
        super().send_email()

#global variables start
config=MassMailerConfig() #create instance of MassMailerConfig and set as global config object
totalEmailsSent=[0,0] #0th index = total emails sent , 1st index = total seconds taken so far

log_file_path="log.txt" #log file
logFile = open(log_file_path, "a") #open in append mode

smtpsQueue=queue.SimpleQueue() #queue to hold smtp servers
emailsQueue=queue.SimpleQueue() #queue to hold recipients' email addresses
proxiesQueue=[] #list to hold all proxy servers
#global variables end